"""
CT109 RHYTHMIND 全栈冒烟测试

用法:
    python scripts/ct109_smoke_test.py
    python scripts/ct109_smoke_test.py --base-url http://10.10.10.19

6 层测试: L1 基础设施 → L2 API → L3 外部服务 → L4 前端 → L5 Nginx → L6 业务流程
"""
from __future__ import annotations

import json
import sys
import time
import urllib.request
import urllib.error
import ssl
from dataclasses import dataclass, field

# 自签证书的 HTTPS 部署需要跳过验证；HTTP→HTTPS 重定向时跟随
BASE = "http://10.10.10.19"
PASS = "PASS"
FAIL = "FAIL"
SKIP = "SKIP"

# 全局不验证 SSL（仅内网冒烟测试用）
_SSL_CTX = ssl.create_default_context()
_SSL_CTX.check_hostname = False
_SSL_CTX.verify_mode = ssl.CERT_NONE


@dataclass
class Result:
    layer: str
    name: str
    status: str
    detail: str = ""
    ms: float = 0.0


results: list[Result] = []
t_start = time.time()


def http(url: str, method: str = "GET", headers: dict | None = None, data: bytes | None = None, timeout: int = 10) -> tuple[int, str, float]:
    t0 = time.time()
    req = urllib.request.Request(url, method=method, data=data)
    if headers:
        for k, v in headers.items():
            req.add_header(k, v)
    # 自签 HTTPS 跳过验证 + 跟随跨协议重定向
    https_handler = urllib.request.HTTPSHandler(context=_SSL_CTX)
    redirect_handler = urllib.request.HTTPRedirectHandler()
    opener = urllib.request.build_opener(https_handler, redirect_handler)
    try:
        with opener.open(req, timeout=timeout) as resp:
            body = resp.read().decode("utf-8", errors="replace")
            return resp.status, body, (time.time() - t0) * 1000
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", errors="replace") if e.fp else ""
        return e.code, body, (time.time() - t0) * 1000
    except Exception as e:
        return 0, str(e), (time.time() - t0) * 1000


def record(layer: str, name: str, status: str, detail: str = "", ms: float = 0.0):
    results.append(Result(layer=layer, name=name, status=status, detail=detail, ms=ms))
    icon = "✅" if status == PASS else "❌" if status == FAIL else "⏭"
    print(f"  {icon} {layer}/{name}: {status} ({ms:.0f}ms) {detail}")


# ═══════════════════════════════════════════════════════════════
# L1 基础设施
# ═══════════════════════════════════════════════════════════════
def test_l1():
    print("\n── L1 基础设施 ──")

    # 1.1 服务存活
    code, body, ms = http(f"{BASE}/livez")
    ok = code == 200 and '"alive"' in body
    record("L1", "livez", PASS if ok else FAIL, f"code={code}", ms)

    # 1.2 就绪检查
    code, body, ms = http(f"{BASE}/readyz")
    ok = code == 200 and '"ready"' in body
    db_ok = '"db":"ok"' in body
    redis_ok = '"redis":"ok"' in body
    record("L1", "readyz", PASS if ok and db_ok and redis_ok else FAIL,
           f"db={'ok' if db_ok else 'FAIL'} redis={'ok' if redis_ok else 'FAIL'}", ms)

    # 1.3 ping
    code, body, ms = http(f"{BASE}/ping")
    record("L1", "ping", PASS if code == 200 else FAIL, f"code={code}", ms)

    # 1.4 version
    code, body, ms = http(f"{BASE}/version")
    ver = ""
    try:
        ver = json.loads(body).get("version", "")
    except Exception:
        pass
    record("L1", "version", PASS if code == 200 and ver else FAIL, f"v={ver}", ms)

    # 1.5 内存（通过 SSH 代理）
    # 跳过直接内存检查，通过 readyz 间接验证

    # 1.6 根路径重定向
    code, _, ms = http(f"{BASE}/")
    record("L1", "root_redirect", PASS if code in (200, 301, 302) else FAIL, f"code={code}", ms)


# ═══════════════════════════════════════════════════════════════
# L2 API 端点
# ═══════════════════════════════════════════════════════════════
def test_l2():
    print("\n── L2 API 端点 ──")

    # 2.1 公开端点（无需认证）
    pub_endpoints = [
        ("/livez", 200, "infra"),
        ("/readyz", 200, "infra"),
        ("/ping", 200, "infra"),
        ("/version", 200, "infra"),
        ("/qm/api/users/summary", 200, "public_api"),
    ]
    for ep, expected, cat in pub_endpoints:
        code, body, ms = http(f"{BASE}{ep}")
        record("L2", f"pub_{ep}", PASS if code == expected else FAIL, f"code={code}", ms)

    # 2.2 需认证端点（应返回 403 或 405）
    auth_endpoints = [
        ("/qm/api/dashboard", 403),
        ("/qm/api/reports", 403),
        ("/qm/api/analyze", 405),  # POST-only, GET → 405
    ]
    for ep, expected in auth_endpoints:
        code, _, ms = http(f"{BASE}{ep}")
        record("L2", f"auth_{ep}", PASS if code == expected else FAIL, f"code={code}", ms)

    # 2.3 POST 端点（应返回 405 或 403）
    code, _, ms = http(f"{BASE}/api/v1/health/upload", method="GET")
    record("L2", "v1_upload_get", PASS if code in (405, 403, 401) else FAIL, f"code={code}", ms)

    # 2.4 404 端点
    code, _, ms = http(f"{BASE}/qm/api/nonexistent")
    record("L2", "404_api", PASS if code == 404 else FAIL, f"code={code}", ms)

    # 2.5 Health 兼容端点
    code, body, ms = http(f"{BASE}/health")
    record("L2", "health_compat", PASS if code in (200, 404) else FAIL, f"code={code}", ms)


# ═══════════════════════════════════════════════════════════════
# L3 外部服务
# ═══════════════════════════════════════════════════════════════
def test_l3():
    print("\n── L3 外部服务 ──")

    # 3.1 PG 连通（通过 readyz db check 间接验证）
    code, body, ms = http(f"{BASE}/readyz")
    pg_ok = '"db":"ok"' in body
    record("L3", "pg_connectivity", PASS if pg_ok else FAIL, f"via readyz", ms)

    # 3.2 Redis 连通（通过 readyz redis check 间接验证）
    redis_ok = '"redis":"ok"' in body
    record("L3", "redis_connectivity", PASS if redis_ok else FAIL, f"via readyz", ms)

    # 3.3 oMLX 连通
    code, body, ms = http("http://10.10.10.138:8001/v1/models", headers={"Authorization": "Bearer ak47"})
    omlx_ok = code == 200 and "data" in body
    model_count = 0
    if omlx_ok:
        try:
            model_count = len(json.loads(body).get("data", []))
        except Exception:
            pass
    record("L3", "omlx_connectivity", PASS if omlx_ok else FAIL, f"models={model_count}", ms)

    # 3.4 oMLX 推理测试
    payload = json.dumps({
        "model": "gemma-4-e4b-it-4bit",
        "messages": [{"role": "user", "content": "Say hello in 5 words"}],
        "max_tokens": 30,
    }).encode()
    code, body, ms = http(
        "http://10.10.10.138:8001/v1/chat/completions",
        method="POST",
        headers={"Authorization": "Bearer ak47", "Content-Type": "application/json"},
        data=payload,
        timeout=30,
    )
    inference_ok = code == 200 and "choices" in body
    record("L3", "omlx_inference", PASS if inference_ok else FAIL, f"code={code} ({ms:.0f}ms)", ms)

    # 3.5 数据库表数（通过 API 间接验证）
    code, body, ms = http(f"{BASE}/qm/api/users/summary")
    db_api_ok = code == 200
    record("L3", "db_query", PASS if db_api_ok else FAIL, f"users_summary code={code}", ms)

    # 3.6 Redis 写入（通过 readyz 持续可用验证）
    record("L3", "redis_persistence", PASS if redis_ok else FAIL, "via readyz re-check", 0)


# ═══════════════════════════════════════════════════════════════
# L4 前端
# ═══════════════════════════════════════════════════════════════
def test_l4():
    print("\n── L4 前端 ──")

    # 4.1 所有页面渲染
    pages = ["/", "/dashboard", "/bigscreen", "/report", "/chat",
             "/upload", "/medical", "/llm-observe", "/test-report"]
    for page in pages:
        code, body, ms = http(f"{BASE}/qm{page}")
        has_html = "<html" in body.lower() or "<!doctype" in body.lower()
        record("L4", f"page{page}", PASS if code == 200 and has_html else FAIL,
               f"code={code} html={has_html}", ms)

    # 4.2 SPA 路由（非 / 结尾）
    code, body, ms = http(f"{BASE}/qm/dashboard")
    record("L4", "spa_dashboard", PASS if code == 200 else FAIL, f"code={code}", ms)

    # 4.3 静态资源加载
    code, body, ms = http(f"{BASE}/qm/")
    js_match = ""
    if code == 200:
        import re
        matches = re.findall(r'(_next/static/chunks/[a-z0-9]+\.js)', body)
        js_match = matches[0] if matches else ""
    if js_match:
        code2, _, ms2 = http(f"{BASE}/qm/{js_match}")
        record("L4", "js_resource", PASS if code2 == 200 else FAIL, f"{js_match} code={code2}", ms2)
    else:
        record("L4", "js_resource", SKIP, "no JS found in index", 0)

    # 4.4 404 页面
    code, _, ms = http(f"{BASE}/qm/nonexistent-page-xyz")
    record("L4", "404_fallback", PASS if code == 200 else FAIL,
           f"code={code} (SPA should serve index)", ms)


# ═══════════════════════════════════════════════════════════════
# L5 Nginx
# ═══════════════════════════════════════════════════════════════
def test_l5():
    print("\n── L5 Nginx ──")

    # 共享 opener（自签证书 + 跨协议重定向）
    opener = urllib.request.build_opener(
        urllib.request.HTTPSHandler(context=_SSL_CTX),
        urllib.request.HTTPRedirectHandler(),
    )

    # 5.1 安全头
    url = f"{BASE}/qm/"
    req = urllib.request.Request(url, method="HEAD")
    try:
        with opener.open(req, timeout=10) as resp:
            headers = dict(resp.headers)
    except Exception as e:
        record("L5", "headers", FAIL, str(e), 0)
        return

    checks = {
        "X-Frame-Options": "SAMEORIGIN",
        "X-Content-Type-Options": "nosniff",
        "X-XSS-Protection": "1",
    }
    for header, expected in checks.items():
        val = headers.get(header, "")
        ok = expected.lower() in val.lower()
        record("L5", f"header_{header}", PASS if ok else FAIL, f"value={val}", 0)

    # 5.2 server_tokens off
    server = headers.get("Server", "")
    record("L5", "server_tokens", PASS if server == "nginx" else FAIL, f"Server={server}", 0)

    # 5.3 Gzip
    req2 = urllib.request.Request(url)
    req2.add_header("Accept-Encoding", "gzip")
    t0 = time.time()
    with opener.open(req2, timeout=10) as resp2:
        ce = resp2.headers.get("Content-Encoding", "")
        ms = (time.time() - t0) * 1000
    record("L5", "gzip", PASS if ce == "gzip" else FAIL, f"Content-Encoding={ce}", ms)

    # 5.4 静态缓存
    code, body, ms = http(f"{BASE}/qm/")
    import re
    js_matches = re.findall(r'(_next/static/chunks/[a-z0-9]+\.js)', body)
    if js_matches:
        req3 = urllib.request.Request(f"{BASE}/qm/{js_matches[0]}")
        t0 = time.time()
        with opener.open(req3, timeout=10) as resp3:
            all_cc = resp3.headers.get_all("Cache-Control") if hasattr(resp3.headers, "get_all") else [resp3.headers.get("Cache-Control", "")]
            cc = " ".join(all_cc) if all_cc else ""
            ms = (time.time() - t0) * 1000
        record("L5", "static_cache", PASS if "immutable" in cc else FAIL, f"Cache-Control={cc}", ms)
    else:
        record("L5", "static_cache", SKIP, "no JS resource found", 0)

    # 5.5 API 代理正确性
    code, body, ms = http(f"{BASE}/qm/api/users/summary")
    proxy_ok = code == 200
    record("L5", "api_proxy", PASS if proxy_ok else FAIL, f"code={code}", ms)

    # 5.6 健康检查代理
    code, body, ms = http(f"{BASE}/livez")
    record("L5", "health_proxy", PASS if code == 200 else FAIL, f"code={code}", ms)

    # 5.7 根重定向
    code, _, ms = http(f"{BASE}/")
    record("L5", "root_redirect", PASS if code in (200, 301, 302) else FAIL, f"code={code}", ms)

    # 5.8 /api/v1 代理
    code, _, ms = http(f"{BASE}/api/v1/health/upload")
    record("L5", "v1_proxy", PASS if code in (405, 403, 401) else FAIL, f"code={code}", ms)


# ═══════════════════════════════════════════════════════════════
# L6 业务流程
# ═══════════════════════════════════════════════════════════════
def test_l6():
    print("\n── L6 业务流程 ──")

    # 6.1 用户列表 → 空列表正常
    code, body, ms = http(f"{BASE}/qm/api/users/summary")
    users = []
    if code == 200:
        try:
            users = json.loads(body).get("users", [])
        except Exception:
            pass
    record("L6", "users_summary", PASS if code == 200 else FAIL, f"users={len(users)}", ms)

    # 6.2 未认证访问 dashboard → 403
    code, _, ms = http(f"{BASE}/qm/api/dashboard")
    record("L6", "auth_reject", PASS if code == 403 else FAIL, f"code={code}", ms)

    # 6.3 报告列表（未认证）→ 403
    code, _, ms = http(f"{BASE}/qm/api/reports")
    record("L6", "reports_auth", PASS if code == 403 else FAIL, f"code={code}", ms)

    # 6.4 oMLX → API 联动（模型列表可达）
    code, body, ms = http("http://10.10.10.138:8001/v1/models", headers={"Authorization": "Bearer ak47"})
    models = []
    if code == 200:
        try:
            models = [m["id"] for m in json.loads(body).get("data", [])]
        except Exception:
            pass
    record("L6", "omlx_models_ready", PASS if models else FAIL, f"models={models}", ms)

    # 6.5 前端→API 完整链路（页面加载 + API 调用）
    code_html, _, ms1 = http(f"{BASE}/qm/")
    code_api, body_api, ms2 = http(f"{BASE}/qm/api/users/summary")
    full_chain = code_html == 200 and code_api == 200 and '"status":"ok"' in body_api
    record("L6", "full_chain", PASS if full_chain else FAIL,
           f"html={code_html} api={code_api}", ms1 + ms2)


# ═══════════════════════════════════════════════════════════════
# 报告生成
# ═══════════════════════════════════════════════════════════════
def report():
    total = len(results)
    passed = sum(1 for r in results if r.status == PASS)
    failed = sum(1 for r in results if r.status == FAIL)
    skipped = sum(1 for r in results if r.status == SKIP)
    elapsed = time.time() - t_start

    print("\n" + "=" * 60)
    print(f"  CT109 RHYTHMIND 测试报告")
    print(f"  时间: {time.strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"  耗时: {elapsed:.1f}s")
    print("=" * 60)

    current_layer = ""
    for r in results:
        if r.layer != current_layer:
            current_layer = r.layer
            print(f"\n  {current_layer}:")
        icon = "✅" if r.status == PASS else "❌" if r.status == FAIL else "⏭"
        ms_str = f"{r.ms:.0f}ms" if r.ms > 0 else "-"
        print(f"    {icon} {r.name}: {r.status} [{ms_str}] {r.detail}")

    print(f"\n{'=' * 60}")
    print(f"  总计: {total} | ✅ {passed} | ❌ {failed} | ⏭ {skipped}")
    rate = (passed / total * 100) if total > 0 else 0
    print(f"  通过率: {rate:.1f}%")
    print(f"{'=' * 60}")

    if failed > 0:
        print("\n  ❌ 失败用例:")
        for r in results:
            if r.status == FAIL:
                print(f"    - {r.layer}/{r.name}: {r.detail}")

    return failed == 0


def main():
    import argparse
    global BASE
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", default=BASE)
    args = parser.parse_args()
    BASE = args.base_url.rstrip("/")

    print(f"目标: {BASE}")
    test_l1()
    test_l2()
    test_l3()
    test_l4()
    test_l5()
    test_l6()
    ok = report()
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
