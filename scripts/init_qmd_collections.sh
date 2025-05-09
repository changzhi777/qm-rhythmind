#!/usr/bin/env bash
# init_qmd_collections.sh — QMD 集合初始化脚本
# 首次部署或 data/ 内容更新后执行
#
# 用法：bash scripts/init_qmd_collections.sh

set -euo pipefail

QMD_URL="${QMD_URL:-http://localhost:8181}"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(dirname "$SCRIPT_DIR")"
DATA_DIR="$ROOT_DIR/data"

echo "🚀 律动 RHYTHMIND — QMD 集合初始化"
echo "   QMD URL: $QMD_URL"
echo "   数据目录: $DATA_DIR"

# 等待 QMD 就绪
echo "⏳ 等待 QMD 服务就绪..."
for i in {1..30}; do
    if curl -sf "$QMD_URL/health" > /dev/null 2>&1; then
        echo "✅ QMD 已就绪"
        break
    fi
    if [ $i -eq 30 ]; then
        echo "❌ QMD 启动超时" && exit 1
    fi
    sleep 2
done

# 索引 agent 技能库
echo "📚 索引 agent_skills..."
find "$DATA_DIR/skills" -name "*.md" | while read -r file; do
    curl -sf -X POST "$QMD_URL/mcp/upsert" \
        -H "Content-Type: application/json" \
        -d "{
            \"collection\": \"agent_skills\",
            \"id\": \"$(basename "$file" .md)\",
            \"content\": $(python3 -c "import json,sys; print(json.dumps(open(sys.argv[1]).read()))" "$file")
        }" > /dev/null
    echo "  ✓ $(basename "$file")"
done

# 索引健康知识库
echo "📚 索引 health_knowledge..."
if [ -d "$DATA_DIR/knowledge" ]; then
    find "$DATA_DIR/knowledge" -name "*.md" | while read -r file; do
        curl -sf -X POST "$QMD_URL/mcp/upsert" \
            -H "Content-Type: application/json" \
            -d "{
                \"collection\": \"health_knowledge\",
                \"id\": \"$(basename "$file" .md)\",
                \"content\": $(python3 -c "import json,sys; print(json.dumps(open(sys.argv[1]).read()))" "$file")
            }" > /dev/null
        echo "  ✓ $(basename "$file")"
    done
fi

# 索引湖南饮食数据库
echo "📚 索引 hunan_diet..."
if [ -d "$DATA_DIR/hunan_diet" ]; then
    find "$DATA_DIR/hunan_diet" -name "*.md" -o -name "*.txt" | while read -r file; do
        curl -sf -X POST "$QMD_URL/mcp/upsert" \
            -H "Content-Type: application/json" \
            -d "{
                \"collection\": \"hunan_diet\",
                \"id\": \"$(basename "$file")\",
                \"content\": $(python3 -c "import json,sys; print(json.dumps(open(sys.argv[1]).read()))" "$file")
            }" > /dev/null
        echo "  ✓ $(basename "$file")"
    done
fi

echo "🎉 QMD 集合初始化完成！"
