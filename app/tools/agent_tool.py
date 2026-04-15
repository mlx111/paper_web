import traceback
from pathlib import Path
from typing import Any, AsyncGenerator, Dict
from deepagents.backends import StateBackend, StoreBackend, CompositeBackend,FilesystemBackend
from langchain.agents import AgentState, create_agent
from langchain.agents.middleware import before_model
from langchain_core.messages import HumanMessage, RemoveMessage, SystemMessage
from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph.message import REMOVE_ALL_MESSAGES
from langgraph.runtime import Runtime
from langgraph.store.memory import InMemoryStore
from loguru import logger
from pydantic import BaseModel, Field
from tools import get_current_time , retrieve_knowledge , web_search ,summary_message
from models.factory import qwen_model
from settings.config import config
from deepagents import create_deep_agent


