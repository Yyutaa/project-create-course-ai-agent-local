"""One renderer for direct Provider messages and their token preflight."""

import json

from langchain_core.prompts import ChatPromptTemplate


def render_agent_messages(request):
    system = {
        "role": request.role,
        "goal": request.goal,
        "instructions": request.instructions,
        "output_schema": request.output_schema,
        "rules": [
            "只返回一个符合 output_schema 的 JSON 对象",
            "不得修改 Run 状态或决定 release",
        ],
    }
    inputs = [item.model_dump(mode="json") for item in request.inputs]
    return ChatPromptTemplate.from_messages(
        [("system", "{system}"), ("human", "{inputs}")]
    ).format_messages(
        system=json.dumps(system, ensure_ascii=False),
        inputs=json.dumps({"inputs": inputs}, ensure_ascii=False),
    )
