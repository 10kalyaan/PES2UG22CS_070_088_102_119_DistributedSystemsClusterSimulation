from flask import Flask, jsonify, request, render_template
import docker
import time
import threading
from collections import defaultdict
from datetime import datetime

app = Flask(__name__)

# Docker client
docker_client = docker.from_env()

# Cluster state
nodes = {}  # {node_id: {'cpu_cores': int, 'pods': list, 'last_heartbeat': timestamp, 'container_id': str}}
pods = {}   # {pod_id: {'cpu_required': int, 'node_id': str, 'created_at': timestamp}}

# ID counters
node_id_counter = 1
pod_id_counter = 1

@app.route('/')
def index():
    return render_template('index.html')

# Node Management Endpoints
@app.route('/nodes', methods=['POST'])
def add_node():
    global node_id_counter
    data = request.json
    cpu_cores = data.get('cpu_cores', 1)
    
    try:
        # Launch a new container for the node
        container = docker_client.containers.run(
            "alpine",
            command="tail -f /dev/null",  # Keep container running
            detach=True,
            name=f"node-{node_id_counter}",
            labels={"cluster-sim": "true"}  # Add label for easy identification
        )
        
        node_id = f"node-{node_id_counter}"
        nodes[node_id] = {
            'cpu_cores': cpu_cores,
            'available_cpu': cpu_cores,
            'pods': [],
            'last_heartbeat': time.time(),
            'container_id': container.id,
            'created_at': datetime.now().isoformat()
        }
        node_id_counter += 1
        
        return jsonify({
            'status': 'success',
            'message': f'Node {node_id} added successfully',
            'node_id': node_id
        }), 201
    except Exception as e:
        return jsonify({
            'status': 'error',
            'message': f'Failed to add node: {str(e)}'
        }), 500

@app.route('/nodes', methods=['GET'])
def list_nodes():
    current_time = time.time()
    node_list = []
    
    for node_id, node_info in nodes.items():
        # Check if node is healthy (heartbeat within last 30 seconds)
        is_healthy = (current_time - node_info['last_heartbeat']) < 30
        
        node_list.append({
            'node_id': node_id,
            'cpu_cores': node_info['cpu_cores'],
            'available_cpu': node_info['available_cpu'],
            'pods': node_info['pods'],
            'pods_count': len(node_info['pods']),
            'status': 'healthy' if is_healthy else 'unhealthy',
            'last_heartbeat': node_info['last_heartbeat'],
            'created_at': node_info['created_at'],
            'container_id': node_info['container_id']
        })
    
    return jsonify({'nodes': node_list})

# Pod Management Endpoints
@app.route('/pods', methods=['POST'])
def launch_pod():
    global pod_id_counter
    data = request.json
    cpu_required = data.get('cpu_required', 1)
    
    # Find a suitable node using first-fit algorithm
    selected_node = None
    for node_id, node_info in nodes.items():
        # Check if node is healthy and has enough resources
        if (time.time() - node_info['last_heartbeat']) < 30 and node_info['available_cpu'] >= cpu_required:
            selected_node = node_id
            break
    
    if not selected_node:
        return jsonify({
            'status': 'error',
            'message': 'No available nodes with sufficient resources'
        }), 400
    
    # Create pod
    pod_id = f"pod-{pod_id_counter}"
    pods[pod_id] = {
        'cpu_required': cpu_required,
        'node_id': selected_node,
        'created_at': datetime.now().isoformat(),
        'status': 'running'
    }
    pod_id_counter += 1
    
    # Update node resources
    nodes[selected_node]['available_cpu'] -= cpu_required
    nodes[selected_node]['pods'].append(pod_id)
    
    return jsonify({
        'status': 'success',
        'message': 'Pod launched successfully',
        'pod_id': pod_id,
        'node_id': selected_node
    })

@app.route('/pods', methods=['GET'])
def list_pods():
    pod_list = []
    for pod_id, pod_info in pods.items():
        pod_list.append({
            'pod_id': pod_id,
            'cpu_required': pod_info['cpu_required'],
            'node_id': pod_info['node_id'],
            'status': pod_info['status'],
            'created_at': pod_info['created_at']
        })
    return jsonify({'pods': pod_list})

# Heartbeat Endpoints
@app.route('/heartbeat/<node_id>', methods=['POST'])
def receive_heartbeat(node_id):
    if node_id not in nodes:
        return jsonify({'status': 'error', 'message': 'Node not found'}), 404
    
    nodes[node_id]['last_heartbeat'] = time.time()
    return jsonify({'status': 'success'})

@app.route('/simulate/heartbeat/<node_id>', methods=['POST'])
def simulate_heartbeat(node_id):
    return receive_heartbeat(node_id)

# Background task to check node health
def check_node_health():
    while True:
        current_time = time.time()
        for node_id, node_info in nodes.items():
            if (current_time - node_info['last_heartbeat']) > 30:
                print(f"Node {node_id} is unhealthy")
        time.sleep(10)

# Start health check thread
health_thread = threading.Thread(target=check_node_health)
health_thread.daemon = True
health_thread.start()

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True)