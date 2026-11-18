from langchain.agents import create_agent
from langgraph.graph import END, START, MessagesState, StateGraph

from app.agent.engine.agents import _MAIN_SYSTEM_MESSAGE, DOMAIN_GUIDANCE, domain_specs
from app.agent.engine.flows import PRESET_FLOWS
from app.agent.tool_registry import effective_registry
from .middleware import as_langchain_tool, middleware


def build_graph(model, route, cancellation):
    registry = effective_registry()
    domains = {domain.name: domain for domain in domain_specs()}
    sequence = PRESET_FLOWS[route.flow_name] if route.strategy == "graph" else ("main_agent",)
    graph = StateGraph(MessagesState)
    previous = START
    for name in sequence:
        if name == "main_agent":
            tools = list(registry.values())
            prompt = _MAIN_SYSTEM_MESSAGE
        elif name == "report_agent":
            tools = [registry["generate_report"]]
            prompt = DOMAIN_GUIDANCE[name] + "。调用 generate_report 汇总本链路已执行的结果。"
        else:
            domain = domains[name]
            tools = [tool for tool in registry.values() if tool.name in domain.tools or tool.scope == "shared"]
            prompt = domain.system_message
        agent = create_agent(model, [as_langchain_tool(t, cancellation) for t in tools if t.is_enabled()],
                             middleware=middleware(), system_prompt=prompt, name=name)
        graph.add_node(name, agent)
        graph.add_edge(previous, name)
        previous = name
    graph.add_edge(previous, END)
    return graph.compile()
