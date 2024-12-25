import streamlit as st
import openai
from langchain_openai import ChatOpenAI
from langchain_groq import ChatGroq
from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder
from langchain_core.messages import HumanMessage, BaseMessage, trim_messages
from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import START, StateGraph
from langgraph.graph.message import add_messages, RemoveMessage
from typing import Annotated, Sequence
from typing_extensions import TypedDict


# Constants
API_PROVIDERS = ('OpenAI', 'Groq')
MODEL_NAMES = {
    'OpenAI': ('gpt-4o-mini', 'gpt-4-turbo', 'gpt-4o'),
    'Groq': ('llama3-70b-8192', 'llama3-8b-8192'),
}
BASE_URLS = {
    'OpenAI': 'https://api.openai.com/v1',
    'Groq': 'https://api.groq.com/openai/v1',
}
KEY_NAMES = {
    'OpenAI': 'OPENAI_API_KEY_DEV',
    'Groq': 'GROQ_API_KEY_DEV',
}


def restart_chat():
    if chatbot:
        if chatbot.get_state(config).values:
            messages = chatbot.get_state(config).values["messages"]
            chatbot.update_state(config, {"messages": [RemoveMessage(id=m.id) for m in messages]})


st.title("🤖 Chatbot with Langchain Framework")
st.caption("🚀 Let's chat with different models using Langchain")


# Sidebar
api_provider = st.sidebar.selectbox(
    label="Which API do you want to use?",
    options=API_PROVIDERS,
    index=0,
    key="api_provider",
    placeholder="Select an API...",
    on_change=restart_chat,
)

model_name = st.sidebar.selectbox(
    label="Which model do you want to use?",
    options=MODEL_NAMES[api_provider],
    index=0,
    key="model_name",
    placeholder="Select a model...",
    on_change=restart_chat,
)

auth_type = st.sidebar.radio(
    "How would you like to authenticate?",
    ["Use an API Key", "Use a Password"],
)

if auth_type == "Use an API Key":
    label = "{} API Key:".format(api_provider)
else:
    label = "Password:"

auth = st.sidebar.text_input(
    label=label,
    key="auth",
    # on_change=restart_chat,
    type="password",
)

@st.cache_data()
def check_openai_api_key(api_key):
    client = openai.OpenAI(
        base_url=BASE_URLS[api_provider],
        api_key=api_key,
    )
    try:
        models = client.models.list()
    except openai.AuthenticationError:
        return False
    except Exception as error:
        st.sidebar.error(error)
    else:
        return True
    

st.session_state["valid_auth"] = False

if auth_type == "Use an API Key":
    if check_openai_api_key(auth):
        api_key = auth
        st.session_state["valid_auth"] = True
        st.sidebar.success("Valid API key")
    else:
        st.sidebar.error("Invalid API key")
else:
    if auth in st.secrets["PASSWORDS"]:
        api_key = st.secrets[KEY_NAMES[api_provider]]
        st.session_state["valid_auth"] = True
        st.sidebar.success("Valid password")
    else:
        st.sidebar.error("Invalid password")


# Layout
st.text_input(
    label="System Prompt:",
    value="You are a helpful assistant.",
    max_chars=1000,
    key="system_prompt",
    help="Top-level instructions for the model's behavior",
    placeholder="System Prompt",
    on_change=restart_chat,
)

stream_enabled = st.checkbox(
    label="Enable stream chat",
    value=True,
    key="stream",
    help="The output will be streaming",
)


prompt_template = ChatPromptTemplate.from_messages(
    [
        (
            "system",
            st.session_state["system_prompt"],
        ),
        MessagesPlaceholder(variable_name="messages"),
    ]
)

@st.cache_resource
def app(api_provider, auth):

    if not auth:
        return None

    if api_provider == "OpenAI":
        llm = ChatOpenAI(model=model_name, api_key=api_key, max_tokens=1000)
    elif api_provider == "Groq":
        llm = ChatGroq(model=model_name, api_key=api_key, max_tokens=1000)
    else:
        pass

    trimmer = trim_messages(
        max_tokens=1000,
        strategy="last",
        token_counter=llm,
        include_system=True,
        allow_partial=False,
        start_on="human",
    )    

    class State(TypedDict):
        messages: Annotated[Sequence[BaseMessage], add_messages]

    workflow = StateGraph(state_schema=State)

    def call_model(state: State):
        trimmed_messages = trimmer.invoke(state["messages"])
        prompt = prompt_template.invoke({"messages": trimmed_messages})
        response = llm.invoke(prompt)
        return {"messages": [response]}

    workflow.add_edge(START, "model")
    workflow.add_node("model", call_model)

    memory = MemorySaver()
    app = workflow.compile(checkpointer=memory)

    return app

chatbot = app(api_provider, auth)

config = {"configurable": {"thread_id": "abc345"}}


# Display system prompt
st.chat_message(name='assistant', avatar="🤖").write(
    st.session_state["system_prompt"]
)

# Display chat history
if chatbot:
    if "messages" in chatbot.get_state(config).values:
        for msg in chatbot.get_state(config).values["messages"]:
            st.chat_message(msg.type).write(msg.content)


# Handle new messages
if query := st.chat_input(disabled=not st.session_state["valid_auth"]):

    st.chat_message(name="human").write(query)

    input_messages = [HumanMessage(query)]

    if not stream_enabled:
        output = chatbot.invoke({"messages": input_messages}, config)
        st.chat_message(name="assistant").write(output["messages"][-1].content)
    else:

        stream = chatbot.stream({"messages": input_messages}, config, stream_mode="messages")

        with st.empty():

            output = ""
            for chunk, metadata in stream:
                output += chunk.content

                st.chat_message(name="assistant").write(output)
                # st.write(output)    
