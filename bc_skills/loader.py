# -*- coding: utf-8 -*-
"""
Business Claw - Skill Loader

Loads and manages skill definitions from YAML/JSON files.
"""

import frappe
import json
import os
from typing import Dict, List, Optional, Any
from pathlib import Path


class SkillLoader:
	"""
	Loads and manages skill definitions.
	
	Skills are pre-defined workflows that combine multiple MCP tools
	into higher-level business operations.
	"""
	
	def __init__(self):
		self.skills_dir = Path(__file__).parent / "definitions"
		self._skills: Dict[str, Dict] = {}
		self._load_all_skills()
	
	def _load_all_skills(self):
		"""Load all skill definitions from the definitions directory."""
		if not self.skills_dir.exists():
			return
		
		for file_path in self.skills_dir.glob("*.json"):
			try:
				skill = self._load_skill_file(file_path)
				if skill:
					self._skills[skill["name"]] = skill
			except Exception as e:
				frappe.log_error(
					f"Failed to load skill {file_path}: {str(e)}",
					"Business Claw Skills"
				)
	
	def _load_skill_file(self, file_path: Path) -> Optional[Dict]:
		"""
		Load a skill definition from a file.
		
		Args:
			file_path: Path to the skill file
			
		Returns:
			Skill definition dict or None
		"""
		with open(file_path, "r") as f:
			if file_path.suffix == ".json":
				return json.load(f)
			elif file_path.suffix in (".yaml", ".yml"):
				try:
					import yaml
					return yaml.safe_load(f)
				except ImportError:
					frappe.logger().warning("PyYAML not installed, skipping YAML skill files")
					return None
		
		return None
	
	def get_skill(self, name: str) -> Optional[Dict]:
		"""
		Get a skill definition by name.
		
		Args:
			name: Skill name
			
		Returns:
			Skill definition or None
		"""
		return self._skills.get(name)
	
	def get_all_skills(self) -> Dict[str, Dict]:
		"""
		Get all loaded skills.
		
		Returns:
			Dict of skill name -> skill definition
		"""
		return self._skills
	
	def get_skill_names(self) -> List[str]:
		"""
		Get list of available skill names.
		
		Returns:
			List of skill names
		"""
		return list(self._skills.keys())
	
	def validate_skill(self, skill: Dict) -> bool:
		"""
		Validate a skill definition.
		
		Args:
			skill: Skill definition to validate
			
		Returns:
			True if valid
		"""
		required_fields = ["name", "description", "tools"]
		
		for field in required_fields:
			if field not in skill:
				return False
		
		# Validate tools
		if not isinstance(skill["tools"], list):
			return False
		
		for tool in skill["tools"]:
			if "name" not in tool:
				return False
		
		return True


# Global skill loader instance
_skill_loader: Optional[SkillLoader] = None


def get_skill_loader() -> SkillLoader:
	"""
	Get the global skill loader instance.
	
	Returns:
		SkillLoader instance
	"""
	global _skill_loader
	if _skill_loader is None:
		_skill_loader = SkillLoader()
	return _skill_loader


def load_skill(name: str) -> Optional[Dict]:
	"""
	Load a skill by name.
	
	Args:
		name: Skill name
		
	Returns:
		Skill definition or None
	"""
	return get_skill_loader().get_skill(name)


def get_available_skills() -> List[str]:
	"""
	Get list of available skill names.
	
	Returns:
		List of skill names
	"""
	return get_skill_loader().get_skill_names()


def execute_skill(name: str, context: Dict, user: str) -> Dict:
	"""
	Execute a skill with the given context.
	
	Args:
		name: Skill name
		context: Execution context with variables
		user: User executing the skill
		
	Returns:
		Execution result
	"""
	from ..bc_mcp.router import ToolRouter
	
	skill = load_skill(name)
	if not skill:
		return {
			"success": False,
			"error": f"Skill not found: {name}"
		}
	
	router = ToolRouter()
	results = []
	
	# Execute each tool in sequence
	for step in skill.get("workflow", {}).get("steps", []):
		tool_name = step.get("tool")
		arguments = step.get("arguments", {})
		
		# Substitute context variables
		arguments = _substitute_variables(arguments, context)
		
		try:
			result = router.execute_tool(tool_name, arguments, user)
			results.append({
				"step": step.get("step", "unknown"),
				"tool": tool_name,
				"success": True,
				"result": result
			})
			
			# Update context with result
			context.update(result)
			
		except Exception as e:
			results.append({
				"step": step.get("step", "unknown"),
				"tool": tool_name,
				"success": False,
				"error": str(e)
			})
			
			# Stop on error unless continue_on_error is set
			if not step.get("continue_on_error"):
				break
	
	return {
		"success": all(r["success"] for r in results),
		"skill": name,
		"results": results
	}


def _substitute_variables(obj: Any, context: Dict) -> Any:
	"""
	Substitute context variables in an object.
	
	Args:
		obj: Object to process
		context: Context with variable values
		
	Returns:
		Object with variables substituted
	"""
	if isinstance(obj, str):
		# Substitute ${var} patterns
		for key, value in context.items():
			obj = obj.replace(f"${{{key}}}", str(value))
		return obj
	elif isinstance(obj, dict):
		return {k: _substitute_variables(v, context) for k, v in obj.items()}
	elif isinstance(obj, list):
		return [_substitute_variables(item, context) for item in obj]
	else:
		return obj
