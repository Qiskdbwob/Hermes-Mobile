#!/usr/bin/env python3
"""Test script to run Hermes Mobile locally"""

import asyncio
import os
import sys
from pathlib import Path

# Add project root to path
project_root = Path(__file__).parent
sys.path.insert(0, str(project_root))

# Load environment
from dotenv import load_dotenv

load_dotenv(project_root / ".env")

# Test imports
print("Testing imports...")

from hermes_mobile.config.settings import get_settings
from hermes_mobile.core.agent import create_mobile_agent, MobileAgent
from hermes_mobile.memory.provider import MobileMemoryProvider
from hermes_mobile.skills.manager import MobileSkillManager

print("✅ All imports successful")

# Test settings
settings = get_settings()
print(f"✅ Settings loaded: {settings.app_name} v{settings.app_version}")
print(f"   Data dir: {settings.get_data_dir()}")
print(f"   Skills dir: {settings.get_skills_dir()}")
print(f"   Memory DB: {settings.get_memory_db_path()}")

# Test memory provider
print("\nTesting memory provider...")
memory = MobileMemoryProvider(
    db_path=settings.get_memory_db_path(),
    encrypt=settings.encrypt_memory,
)
stats = asyncio.run(memory.get_stats())
print(f"✅ Memory provider initialized: {stats}")

# Test skill manager
print("\nTesting skill manager...")
skill_manager = MobileSkillManager(skills_dir=settings.get_skills_dir())
skills = skill_manager.get_all_skills()
print(f"✅ Skill manager initialized: {len(skills)} skills loaded")

# Test agent creation
print("\nTesting agent creation...")
agent = create_mobile_agent()
print(f"✅ Agent created: {agent.model} via {agent.provider}")
print(f"   Tools available: {len(agent.tools)}")

# Test tool schemas
schemas = agent.get_tool_schemas()
print(f"   Tool schemas: {len(schemas)}")
for schema in schemas[:3]:
    print(f"     - {schema['function']['name']}: {schema['function']['description'][:50]}...")

# Cleanup
memory.close()
print("\n✅ All tests passed!")
