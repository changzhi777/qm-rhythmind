# ─────────────────────────────────────────────────────────────────────────────
# RHYTHMIND 律动 — Multi-agent AI Health Platform
# 作者：外星动物（常智）/ IoTchange  |  邮箱：14455975@qq.com
# 版权所有 (C) 2024-2025 外星动物（常智）/ IoTchange
# 许可：CC BY-NC 4.0  |  商业授权：14455975@qq.com
# ─────────────────────────────────────────────────────────────────────────────

"""
adapters/mlx_adapter.py — Apple Silicon MLX 本地推理适配器

目标硬件：M4 Mac mini 16GB（统一内存，~13GB 可用于模型）
默认模型：mlx-community/Qwen3-30B-A3B-4bit（MoE，激活参数 ~3B，内存占用 ~6GB）

核心设计：
  1. 模块级 _MODEL_CACHE：首次加载后驻留内存，后续调用零启动开销
  2. asyncio.Semaphore：限制并发重型推理（默认 1，防 OOM）
  3. asyncio.to_thread：将同步 generate() 包装为协程，不阻塞事件循环
  4. Qwen3 thinking 模式：默认关闭（速度优先），可通过参数或全局配置开启

Qwen3 thinking 控制：
  - tokenizer.apply_chat_template(..., enable_thinking=False)  — 推荐
  - 若 tokenizer 不支持该参数 → fallback：在 user 消息前插入 "/no_think"
  - 若输出仍含 <think> 块 → 用正则剥离

安装：
  pip install mlx-lm
  # 模型自动下载到 ~/.cache/huggingface/hub/（首次 load 时）
"""
from __future__ import annotations

import asyncio
import logging
import re
from typing import Any

from rhythmind.adapters.model_adapter import ModelAdapter

logger = logging.getLogger(__name__)

# ── mlx-lm 模块级导入（便于 unittest.mock.patch 拦截）───────────────────────
# mlx-lm 仅在 Apple Silicon 上安装；测试环境通过 patch 注入 mock
try:
    from mlx_lm import generate, load  # type: ignore[import]
except ImportError:  # pragma: no cover
    load = None      # type: ignore[assignment]
    generate = None  # type: ignore[assignment]

# ── 模块级模型缓存（进程生命周期内驻留）────────────────────────────────────
_MODEL_CACHE: dict[str, tuple[Any, Any]] = {}  # model_path → (model, tokenizer)

# ── 并发信号量（懒初始化，避免模块导入时触发 event loop 问题）──────────────
_MLX_SEMAPHORE: asyncio.Semaphore | None = None


def _get_semaphore(limit: int = 1) -> asyncio.Semaphore:
    """获取全局 MLX 推理信号量（只在第一次使用所在的 event loop 创建）。"""
    global _MLX_SEMAPHORE
    if _MLX_SEMAPHORE is None:
        _MLX_SEMAPHORE = asyncio.Semaphore(limit)
    return _MLX_SEMAPHORE


# ── Qwen3 thinking 标签清理 ───────────────────────────────────────────────
_THINK_PATTERN = re.compile(r"<think>.*?</think>", re.DOTALL)


def _strip_think_tags(text: str) -> str:
    # 第一步：剥离完整块（不论是否闭合）
    text = _THINK_PATTERN.sub("", text)
    # 第二步：清除残余的未闭合标签（模型输出截断时可能出现）
    text = re.sub(r"<think>|", "", text).strip()
    return text


class MLXAdapter(ModelAdapter):
    """
    Apple Silicon MLX 本地推理适配器。

    线程安全：_MODEL_CACHE 在同一进程内共享，同一 model_path
    只加载一次（dict 写入是 GIL 保护的）。

    并发安全：asyncio.Semaphore 限制同时推理数量，防止 M4 16GB OOM。
    """

    def __init__(
        self,
        model_path: str,
        *,
        thinking: bool | None = None,
        max_tokens: int | None = None,
        semaphore_limit: int | None = None,
    ) -> None:
        """
        Args:
            model_path:      HuggingFace repo 或本地路径，如
                             "mlx-community/Qwen3-30B-A3B-4bit"
                             "~/.cache/rhythmind/mlx/qwen3-30b"
            thinking:        Qwen3 thinking 模式开关。None = 读 settings.mlx_thinking_mode
            max_tokens:      最大输出 token。None = 读 settings.mlx_max_tokens
            semaphore_limit: 并发推理上限。None = 读 settings.mlx_semaphore_limit
        """
        from rhythmind.config import settings

        self._model_path = model_path
        self._thinking: bool = (
            thinking if thinking is not None else settings.mlx_thinking_mode
        )
        self._max_tokens: int = max_tokens or settings.mlx_max_tokens
        self._sem_limit: int = semaphore_limit or settings.mlx_semaphore_limit

    # ── 接口实现 ──────────────────────────────────────────────────────────

    @property
    def model_id(self) -> str:
        return f"mlx://{self._model_path}"

    async def chat(
        self,
        messages: list[dict[str, Any]],
        *,
        temperature: float = 0.3,
        max_tokens: int | None = None,
        response_format: dict[str, Any] | None = None,
        thinking: bool | None = None,
        **kwargs: Any,
    ) -> str:
        """
        异步 MLX 推理（内部用 asyncio.to_thread 包装同步 generate）。

        Args:
            thinking: 覆盖实例级 thinking 配置（单次调用有效）
        """
        sem = _get_semaphore(self._sem_limit)
        effective_thinking = thinking if thinking is not None else self._thinking
        effective_max_tokens = max_tokens or self._max_tokens

        async with sem:
            return await asyncio.to_thread(
                self._generate_sync,
                messages,
                temperature=temperature,
                max_tokens=effective_max_tokens,
                thinking=effective_thinking,
            )

    async def health_check(self) -> bool:
        """检查 mlx-lm 是否已安装（模块级 load 非 None 即为已安装）。"""
        available = load is not None
        if not available:
            logger.warning("mlx_adapter.health_check: mlx-lm not installed")
        return available

    # ── 内部同步方法（在线程池内执行）────────────────────────────────────

    def _load(self) -> tuple[Any, Any]:
        """
        加载模型（首次调用时从 HuggingFace 下载或从本地读取）。

        返回 (model, tokenizer)，结果缓存到 _MODEL_CACHE。
        """
        if self._model_path not in _MODEL_CACHE:
            logger.info("mlx_adapter.loading model=%s", self._model_path)
            model, tokenizer = load(self._model_path)  # 使用模块级 load
            _MODEL_CACHE[self._model_path] = (model, tokenizer)
            logger.info("mlx_adapter.loaded model=%s", self._model_path)
        return _MODEL_CACHE[self._model_path]

    def _build_prompt(
        self,
        messages: list[dict[str, Any]],
        tokenizer: Any,
        thinking: bool,
    ) -> str:
        """
        将 OpenAI messages 格式转换为模型 prompt 字符串。

        优先使用 tokenizer.apply_chat_template（支持 Qwen3 enable_thinking 参数）。
        Fallback：拼接 role: content 文本。
        """
        if not hasattr(tokenizer, "apply_chat_template"):
            # 极少数旧 tokenizer 没有 chat template
            return "\n".join(
                f"{m.get('role', 'user')}: {m.get('content', '')}"
                for m in messages
            )

        base_kwargs: dict[str, Any] = {
            "tokenize": False,
            "add_generation_prompt": True,
        }

        # Qwen3 支持 enable_thinking 参数（控制 CoT 推理模式）
        try:
            return tokenizer.apply_chat_template(
                messages,
                enable_thinking=thinking,
                **base_kwargs,
            )
        except TypeError:
            # 其他模型的 tokenizer 不接受 enable_thinking
            prompt = tokenizer.apply_chat_template(messages, **base_kwargs)
            # 如果需要关闭 thinking 且 tokenizer 不支持，在 user 消息前插入 /no_think
            if not thinking:
                prompt = "/no_think\n" + prompt
            return prompt

    def _generate_sync(
        self,
        messages: list[dict[str, Any]],
        *,
        temperature: float,
        max_tokens: int,
        thinking: bool,
    ) -> str:
        """
        同步生成文本（在线程池内运行，不阻塞 asyncio 事件循环）。

        1. 加载/获取缓存模型
        2. 构建 prompt（含 thinking 模式控制）
        3. 调用 mlx_lm.generate()
        4. 如有 thinking 标签则剥离
        """
        model, tokenizer = self._load()
        prompt = self._build_prompt(messages, tokenizer, thinking)

        response: str = generate(
            model,
            tokenizer,
            prompt=prompt,
            max_tokens=max_tokens,
            temp=temperature,
            verbose=False,
        )

        # 关闭 thinking 时剥离残余的 <think>...</think> 块
        if not thinking and "<think>" in response:
            response = _strip_think_tags(response)

        logger.debug(
            "mlx_adapter.generate model=%s tokens_out=%d thinking=%s",
            self._model_path,
            len(response.split()),  # 近似 token 计数
            thinking,
        )
        return response
