from flask import Flask, jsonify
from orchestrator.diagnostics_orchestrator import SystemDiagnosticsOrchestrator

# Initialize Flask app and orchestrator
app = Flask(__name__)
orchestrator = SystemDiagnosticsOrchestrator()

@app.route("/", methods=["GET"])
def home():
    return "<h1>Universal Hardware Assistant API</h1><p>Welcome to the system diagnostics API. Use /recommendations to get started.</p>"

@app.route("/favicon.ico")
def favicon():
    return "", 204  # Return "No Content"

@app.route("/recommendations", methods=["GET"])
def recommendations():
    # Process diagnostics and recommendations
    result = orchestrator.process_diagnostics()
    return jsonify(result)

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)
