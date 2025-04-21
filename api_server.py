from flask import Flask, jsonify, request, render_template
import docker
import time
import threading
from collections import defaultdict
from datetime import datetime
import random
from enum import Enum

app = Flask(__name__)

# Docker client
docker_client = docker.from_env()

# Cluster state
nodes = {}  # {node_id: {'cpu_cores': int, 'pods': list, 'last_heartbeat': timestamp, 'container_id': str}}
pods = {}   # {pod_id: {'cpu_required': int, 'node_id': str, 'created_at': timestamp}}

# ID counters
node_id_counter = 1
pod_id_counter = 1

class SchedulingAlgorithm(Enum):
    FIRST_FIT = "first_fit"
    BEST_FIT = "best_fit"
    WORST_FIT = "worst_fit"

def select_node(cpu_required, algorithm):
    healthy_nodes = [node_id for node_id, node_info in nodes.items() 
                    if (time.time() - node_info['last_heartbeat']) < 30 
                    and node_info['available_cpu'] >= cpu_required]
    
    if not healthy_nodes:
        return None
    
    if algorithm == SchedulingAlgorithm.FIRST_FIT.value:
        # First-Fit: Select the first node that has enough resources
        for node_id in healthy_nodes:
            if nodes[node_id]['available_cpu'] >= cpu_required:
                return node_id
    
    elif algorithm == SchedulingAlgorithm.BEST_FIT.value:
        # Best-Fit: Select the node with the smallest available CPU that can fit the pod
        best_node = None
        min_diff = float('inf')
        
        for node_id in healthy_nodes:
            available = nodes[node_id]['available_cpu']
            if available >= cpu_required:
                diff = available - cpu_required
                if diff < min_diff:
                    min_diff = diff
                    best_node = node_id
        
        return best_node
    
    elif algorithm == SchedulingAlgorithm.WORST_FIT.value:
        # Worst-Fit: Select the node with the largest available CPU
        worst_node = None
        max_available = -1
        
        for node_id in healthy_nodes:
            available = nodes[node_id]['available_cpu']
            if available >= cpu_required and available > max_available:
                max_available = available
                worst_node = node_id
        
        return worst_node
    
    return None

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
        # First check if container exists and is running
        container_running = False
        try:
            container = docker_client.containers.get(node_info['container_id'])
            container_running = container.status == 'running'
        except:
            pass
        
        # Determine node status
        if not container_running:
            status = 'terminated'
            # Ensure we've attempted to reschedule pods
            if node_info.get('status') != 'terminated':
                reschedule_pods_from_failed_node(node_id)
        elif (current_time - node_info['last_heartbeat']) > 30:
            status = 'unhealthy'
        else:
            status = 'healthy'
        
        # Update node status in our records
        nodes[node_id]['status'] = status
        
        node_list.append({
            'node_id': node_id,
            'cpu_cores': node_info['cpu_cores'],
            'available_cpu': node_info['available_cpu'],
            'pods': node_info['pods'],
            'pods_count': len(node_info['pods']),
            'status': status,
            'last_heartbeat': node_info['last_heartbeat'],
            'created_at': node_info['created_at'],
            'container_id': node_info['container_id'],
            'container_running': container_running
        })
    
    return jsonify({'nodes': node_list})


# Pod Management Endpoints
# Modify the launch_pod endpoint to use the selected algorithm
@app.route('/pods', methods=['POST'])
def launch_pod():
    global pod_id_counter
    data = request.json
    cpu_required = data.get('cpu_required', 1)
    algorithm = data.get('algorithm', SchedulingAlgorithm.FIRST_FIT.value)
    
    # Find a suitable node using the selected algorithm
    selected_node = select_node(cpu_required, algorithm)
    
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

def reschedule_pods_from_failed_node(failed_node_id):
    if failed_node_id not in nodes:
        return
    
    # Get all pods that were on the failed node
    pods_to_reschedule = [pod_id for pod_id, pod_info in pods.items()
                         if pod_info['node_id'] == failed_node_id]
    
    if not pods_to_reschedule:
        return
    
    print(f"Attempting to reschedule {len(pods_to_reschedule)} pods from failed node {failed_node_id}")
    
    rescheduled_count = 0
    for pod_id in pods_to_reschedule:
        pod_info = pods[pod_id]
        
        # Skip if already rescheduled or failed
        if pod_info['status'] in ['rescheduled', 'failed']:
            continue
            
        cpu_required = pod_info['cpu_required']
        
        # Mark as rescheduling
        pod_info['status'] = 'rescheduling'
        
        # Try to find a new node (using first-fit for rescheduling)
        new_node = select_node(cpu_required, SchedulingAlgorithm.FIRST_FIT.value)
        
        if new_node:
            # Free resources from old node
            nodes[failed_node_id]['available_cpu'] += cpu_required
            if pod_id in nodes[failed_node_id]['pods']:
                nodes[failed_node_id]['pods'].remove(pod_id)
            
            # Allocate to new node
            pod_info['node_id'] = new_node
            pod_info['status'] = 'running'
            nodes[new_node]['pods'].append(pod_id)
            nodes[new_node]['available_cpu'] -= cpu_required
            rescheduled_count += 1
            print(f"Rescheduled pod {pod_id} to node {new_node}")
        else:
            pod_info['status'] = 'failed'
            print(f"Could not reschedule pod {pod_id} - no available nodes")
    
    print(f"Rescheduled {rescheduled_count} pods from node {failed_node_id}")
    
    # If all pods rescheduled, we can optionally remove the failed node
    if all(pod_info['status'] != 'running' for pod_id, pod_info in pods.items() 
           if pod_info['node_id'] == failed_node_id):
        print(f"All pods rescheduled from {failed_node_id}, removing from cluster")
        del nodes[failed_node_id]

# Modify the health check thread to handle pod rescheduling
def check_node_health():
    while True:
        current_time = time.time()
        
        # First check all containers
        for node_id, node_info in list(nodes.items()):
            try:
                container = docker_client.containers.get(node_info['container_id'])
                if container.status != 'running':
                    print(f"Container for node {node_id} is not running, status: {container.status}")
                    reschedule_pods_from_failed_node(node_id)
                    nodes[node_id]['status'] = 'terminated'
            except Exception as e:
                print(f"Container for node {node_id} not found: {str(e)}")
                reschedule_pods_from_failed_node(node_id)
                nodes[node_id]['status'] = 'terminated'
        
        # Then check heartbeats
        for node_id, node_info in nodes.items():
            if node_info.get('status') == 'terminated':
                continue
                
            if (current_time - node_info['last_heartbeat']) > 30:
                print(f"Node {node_id} missed heartbeat")
                reschedule_pods_from_failed_node(node_id)
                nodes[node_id]['status'] = 'unhealthy'
        
        time.sleep(3)  # Check every 3 seconds

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

@app.route('/scheduling-algorithms', methods=['GET'])
def get_scheduling_algorithms():
    return jsonify({
        'algorithms': [alg.value for alg in SchedulingAlgorithm],
        'default': SchedulingAlgorithm.FIRST_FIT.value
    })

# Add this function to simulate automatic heartbeats
def simulate_automatic_heartbeats():
    while True:
        for node_id in nodes:
            # Random jitter to simulate real-world conditions
            if random.random() < 0.9:  # 90% chance to send heartbeat
                nodes[node_id]['last_heartbeat'] = time.time()
        
        # Sleep for a random interval between 5-15 seconds
        time.sleep(random.uniform(5, 15))

# Start automatic heartbeat thread
heartbeat_thread = threading.Thread(target=simulate_automatic_heartbeats)
heartbeat_thread.daemon = True
heartbeat_thread.start()

# Start health check thread
health_thread = threading.Thread(target=check_node_health)
health_thread.daemon = True
health_thread.start()

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True)