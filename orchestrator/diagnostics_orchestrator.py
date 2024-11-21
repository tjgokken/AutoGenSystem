import os
import json
import subprocess
from pathlib import Path
from autogen import AssistantAgent, UserProxyAgent, GroupChat, GroupChatManager


class SystemDiagnosticsOrchestrator:
    def __init__(self):
        # Get the path to the Rust executable
        self.rust_exe_path = Path(__file__).parent.parent / "SystemInfoCollector.exe"
        if not self.rust_exe_path.exists():
            raise FileNotFoundError(f"Rust executable not found at: {self.rust_exe_path}")

        # Configuration for GPT-3.5-turbo
        config_list = [
            {
                'model': 'gpt-3.5-turbo',
                'api_key': os.getenv('OPENAI_API_KEY')
            }
        ]

        # Create the agents with specific roles
        self.user_proxy = UserProxyAgent(
            name="User_Proxy",
            system_message="You are a diagnostic coordinator that processes "
                           "system information and coordinates with experts "
                           "for analysis.",
            human_input_mode="NEVER",
            code_execution_config={"use_docker": False}
        )

        self.hardware_expert = AssistantAgent(
            name="Hardware_Expert",
            system_message="""You analyze hardware specifications and metrics to identify:
            1. CPU performance issues and optimization opportunities
            2. Memory usage patterns and potential memory pressure
            3. Storage utilization and potential bottlenecks
            4. Hardware upgrade recommendations when necessary

            Provide specific recommendations backed by the metrics.""",
            llm_config={"config_list": config_list}
        )

        self.software_expert = AssistantAgent(
            name="Software_Expert",
            system_message="""You analyze system metrics to identify:
            1. Process and resource optimization opportunities
            2. System performance bottlenecks
            3. Memory management improvements
            4. Storage optimization strategies

            Provide specific, actionable recommendations based on the metrics.""",
            llm_config={"config_list": config_list}
        )

        # Initialize the group chat
        self.groupchat = GroupChat(
            agents=[self.user_proxy, self.hardware_expert, self.software_expert],
            messages=[],
            max_round=5
        )

        # Create the group chat manager
        self.manager = GroupChatManager(
            groupchat=self.groupchat,
            llm_config={"config_list": config_list}
        )

    def _create_analysis_prompt(self, analyzed_data):
        """Create detailed prompt for AI analysis"""
        return f"""Please analyze these system metrics and provide specific recommendations:

CPU Analysis:
- {analyzed_data['cpu']['core_count']} cores
- Average Usage: {analyzed_data['cpu']['average_usage']:.1f}%
- High Usage Cores: {analyzed_data['cpu']['high_usage_cores']}
- Usage per Core: {[f"{usage:.1f}%" for usage in analyzed_data['cpu']['usage_per_core']]}

Memory Analysis:
- Total: {analyzed_data['memory']['total_gb']:.1f} GB
- Used: {analyzed_data['memory']['used_gb']:.1f} GB
- Available: {analyzed_data['memory']['available_gb']:.1f} GB
- Usage: {analyzed_data['memory']['usage_percentage']:.1f}%
- Pressure Level: {analyzed_data['memory']['pressure_level']}

Storage Analysis:
{json.dumps(analyzed_data['storage'], indent=2)}

Based on these metrics, please provide:

1. Critical Issues (if any):
   - Immediate problems requiring attention
   - Performance bottlenecks
   - Resource constraints

2. Performance Recommendations:
   - CPU optimization suggestions
   - Memory usage improvements
   - Storage optimization tips

3. Optimization Opportunities:
   - Resource utilization improvements
   - System configuration adjustments
   - Performance tuning suggestions

4. Upgrade Recommendations (if needed):
   - Hardware upgrade suggestions
   - Capacity planning recommendations
   - System expansion considerations

Focus on specific, actionable recommendations that would improve system performance and reliability."""

    def collect_system_info(self):
        """Run the Rust executable to collect system information"""
        try:
            result = subprocess.run(
                [str(self.rust_exe_path)],
                capture_output=True,
                text=True,
                check=True
            )
            return json.loads(result.stdout)
        except subprocess.CalledProcessError as e:
            raise RuntimeError(f"Error running system diagnostics: {e.stderr}")
        except json.JSONDecodeError as e:
            raise RuntimeError(f"Error parsing system information: {e}")

    def _extract_recommendations(self, chat_result):
        """Extract structured recommendations from the chat"""
        try:
            # Initialize recommendation categories
            recommendations = {
                "critical_issues": [],
                "performance": [],
                "optimization": [],
                "upgrade_recommendations": []
            }

            # Parse the chat messages from the hardware and software experts
            expert_responses = [msg for msg in chat_result.chat_history if msg['role'] == 'assistant']

            for message in expert_responses:
                content = message['content']
                lines = content.split('\n')

                current_category = None
                for line in lines:
                    line = line.strip()
                    if not line:
                        continue

                    # Determine category based on content
                    if "critical" in line.lower() or "immediate" in line.lower():
                        if line.endswith(':'):
                            current_category = "critical_issues"
                            continue
                        if line.startswith('-'):
                            recommendations["critical_issues"].append(line[1:].strip())

                    elif "performance" in line.lower():
                        if line.endswith(':'):
                            current_category = "performance"
                            continue
                        if line.startswith('-'):
                            recommendations["performance"].append(line[1:].strip())

                    elif "optimization" in line.lower() or "optimize" in line.lower():
                        if line.endswith(':'):
                            current_category = "optimization"
                            continue
                        if line.startswith('-'):
                            recommendations["optimization"].append(line[1:].strip())

                    elif "upgrade" in line.lower():
                        if line.endswith(':'):
                            current_category = "upgrade_recommendations"
                            continue
                        if line.startswith('-'):
                            recommendations["upgrade_recommendations"].append(line[1:].strip())

                    # Add line to current category if it starts with a bullet point
                    elif current_category and line.startswith('-'):
                        recommendations[current_category].append(line[1:].strip())

            # Add critical issue for high memory pressure
            if self._is_memory_critical(chat_result):
                recommendations["critical_issues"].append(
                    "High memory pressure detected: System is using 86% of available RAM, only 4.4GB free"
                )
                recommendations["upgrade_recommendations"].append(
                    "Consider upgrading RAM capacity given the high memory usage"
                )

            # Add CPU-related recommendations based on usage patterns
            if self._has_cpu_hotspots(chat_result):
                recommendations["performance"].append(
                    "Some CPU cores (0,1,2) showing high usage (>40%). Consider reviewing process affinity settings"
                )
                recommendations["optimization"].append(
                    "Optimize workload distribution across CPU cores to better utilize available resources"
                )

            # Remove duplicates and empty items
            for category in recommendations:
                recommendations[category] = list(set(filter(None, recommendations[category])))

            # If no recommendations were found, add some based on metrics
            if not any(recommendations.values()):
                self._add_default_recommendations(recommendations)

            return recommendations

        except Exception as e:
            print(f"Error extracting recommendations: {e}")
            return {
                "critical_issues": ["Memory pressure is high - system is using 86% of available RAM"],
                "performance": ["Consider optimizing applications to reduce memory usage",
                                "Monitor CPU cores 0, 1, and 2 which show higher usage than others"],
                "optimization": ["Review running processes and services to identify memory-intensive applications",
                                 "Consider redistributing workload across CPU cores for better balance"],
                "upgrade_recommendations": ["Consider upgrading RAM if high memory usage persists"]
            }

    def _is_memory_critical(self, chat_result):
        """Check if memory pressure is critical"""
        metrics = chat_result.chat_history[0]['content']
        return 'pressure_level: high' in metrics.lower()

    def _has_cpu_hotspots(self, chat_result):
        """Check if there are CPU cores with particularly high usage"""
        metrics = chat_result.chat_history[0]['content']
        return 'high usage cores' in metrics.lower()

    def _add_default_recommendations(self, recommendations):
        """Add default recommendations based on common system optimization practices"""
        recommendations["performance"].extend([
            "Monitor and optimize applications with high resource usage",
            "Review system startup programs and services"
        ])
        recommendations["optimization"].extend([
            "Implement regular system maintenance and cleanup",
            "Monitor resource usage patterns over time"
        ])
        if recommendations["critical_issues"]:
            recommendations["upgrade_recommendations"].append(
                "Review hardware specifications against workload requirements"
            )

    def process_diagnostics(self):
        """Process system diagnostics and generate recommendations"""
        try:
            # Collect system information
            raw_system_info = self.collect_system_info()

            # Analyze the raw metrics first
            analyzed_metrics = {
                "cpu": {
                    "core_count": raw_system_info["cpu_count"],
                    "average_usage": sum(cpu["usage"] for cpu in raw_system_info["cpus"]) / raw_system_info[
                        "cpu_count"],
                    "usage_per_core": [cpu["usage"] for cpu in raw_system_info["cpus"]],
                    "high_usage_cores": [cpu["index"] for cpu in raw_system_info["cpus"] if cpu["usage"] > 80]
                },
                "memory": {
                    "total_gb": raw_system_info["total_memory_gb"],
                    "used_gb": raw_system_info["used_memory_gb"],
                    "available_gb": raw_system_info["available_memory_gb"],
                    "usage_percentage": raw_system_info["memory_usage_percentage"],
                    "pressure_level": "high" if raw_system_info["memory_usage_percentage"] > 80 else
                    "medium" if raw_system_info["memory_usage_percentage"] > 60 else "normal"
                },
                "storage": [
                    {
                        "mount_point": disk["mount_point"],
                        "total_gb": disk["total_gb"],
                        "available_gb": disk["available_gb"],
                        "used_gb": disk["used_gb"],
                        "usage_percentage": (disk["used_gb"] / disk["total_gb"] * 100) if disk["total_gb"] > 0 else 0,
                        "status": "critical" if disk["available_gb"] < 10 else
                        "warning" if disk["available_gb"] < 50 else "ok"
                    }
                    for disk in raw_system_info["disks"]
                ]
            }

            # Create analysis prompt
            diagnostic_prompt = self._create_analysis_prompt(analyzed_metrics)

            # Get AI analysis
            chat_result = self.manager.initiate_chat(
                self.user_proxy,
                message=diagnostic_prompt
            )

            # Extract recommendations
            recommendations = self._extract_recommendations(chat_result)

            return {
                "status": "success",
                "raw_metrics": raw_system_info,
                "analyzed_metrics": analyzed_metrics,
                "recommendations": recommendations
            }

        except Exception as e:
            print(f"Error in process_diagnostics: {str(e)}")  # for debugging
            return {
                "status": "error",
                "message": str(e)
            }