import yaml
import os

class ToolManager:
    def __init__(self, tool_list):
        # Load config from yaml file
        yaml_path = os.path.join(os.path.dirname(__file__), "config.yaml")
        
        with open(yaml_path, "r") as file:
            self.app_tool_mapping = yaml.safe_load(file)

        tool_name_list = [t.name for t in tool_list]

        self.tools = {}
        for app, tool_entries in self.app_tool_mapping.items():
            for tool in tool_entries:
                tool_name = tool["name"]
                if tool_name in tool_name_list:
                    self.tools[tool_name] = {
                        "app": app,
                        "data_export": tool.get("data_export", False)
                    }

        self.apps = [app for app, tools in self.app_tool_mapping.items() if any(tool["name"] in tool_name_list for tool in tools)]
    
    def get_app_from_tool(self, tool_name):
        """Return the app name of the given tool"""
        return self.tools.get(tool_name, {}).get("app")
    
    def get_app_id_from_tool(self, tool_name):
        """Return the app id of the given tool"""
        app_name = self.get_app_from_tool(tool_name)
        if app_name is not None:
            return self.apps.index(app_name) + 1
        return None

    def get_apps(self):
        return self.apps
    
    def get_tools_from_app_id(self, app_id):
        if int(app_id) == 0:
            return []
        return [t["name"] for t in self.app_tool_mapping[self.apps[int(app_id) - 1]]]
    
    def is_data_export_tool(self, tool_name):
        return self.tools.get(tool_name, {}).get("data_export", False)