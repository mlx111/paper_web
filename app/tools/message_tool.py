from models.factory import qwen_model
from langgraph.checkpoint.memory import MemorySaver
from langchain.agents import create_agent
from langchain.messages import HumanMessage,SystemMessage
def init_message_agent():
    agent=create_agent(
        model=qwen_model.init_model(False),
        system_prompt='''你是一个总结历史对话的专家''',
        checkpointer=MemorySaver(),
        tools=[],
        name="用于总结对话的subagent"
    )
    return agent

def get_query(messages):
    old_messages="\n".join([
        f"{'用户' if msg.type == 'human' else 'AI'}: {msg.content}"
        for msg in messages
    ])
    prompt=f"""
    现在有这样的历史对话:{old_messages},你是一个总结agent历史记录的专家，请你根据前面的历史对话压缩成简洁摘要，只保留：
1. 用户身份信息
2. 重要事实
3. 待办事项
4. 已达成的结论
    """
    return prompt
    
'''@tool(
    name_or_callable="summary_messages",
    description="当用户的对话超过10轮的时候，调用该工具进行历史记录的总结,总结的部分是历史对话的前5轮，后五轮保留"
)'''
def summary_message(messages):
    agent= init_message_agent()
    query=get_query(messages)
    result=agent.invoke({
            "messages": [HumanMessage(content=query)]
        })
    last_result=result.get("messages",[])[-1]
    summary= last_result.content if hasattr(last_result, "content") else str(last_result)
    return SystemMessage(content=f"前面的对话记录的总结是:\n{summary}")