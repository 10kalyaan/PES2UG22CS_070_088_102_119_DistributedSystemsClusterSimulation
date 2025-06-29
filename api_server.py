from flask import Flask, jsonify, request, render_template
import docker
import time
import threading
from collections import defaultdict
from datetime import datetime
import random
from enum import Enum

app = Flask(__name__)
docker_client = docker.from_env()
nodes = {}  
pods = {}  

node_id_counter = 1
pod_id_counter = 1

class SchedulingAlgorithm(Enum):
    FIRST_FIT = "first_fit"
    BEST_FIT = "best_fit"
    WORST_FIT = "worst_fit"

def select_node(cpu_required, algorithm):
    healthy_nodes = [node_id for node_id, node_info in nodes.items() 
                    if node_info.get('status') == 'healthy'
                    and node_info['available_cpu'] >= cpu_required]
    
    if not healthy_nodes:
        return None
    
    if algorithm == SchedulingAlgorithm.FIRST_FIT.value:
        for node_id in healthy_nodes:
            if nodes[node_id]['available_cpu'] >= cpu_required:
                return node_id
    
    elif algorithm == SchedulingAlgorithm.BEST_FIT.value:
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
@app.route('/nodes', methods=['POST'])
def add_node():
    global node_id_counter
    data = request.json
    cpu_cores = data.get('cpu_cores', 1)
    
    try:
        container = docker_client.containers.run(
            "alpine",
            command="tail -f /dev/null", 
            detach=True,
            name=f"node-{node_id_counter}",
            labels={"cluster-sim": "true"}  
        )
        
        node_id = f"node-{node_id_counter}"
        nodes[node_id] = {
            'cpu_cores': cpu_cores,
            'available_cpu': cpu_cores,
            'pods': [],
            'last_heartbeat': time.time(),
            'container_id': container.id,
            'created_at': datetime.now().isoformat(),
            'status': 'healthy' 
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
        container_running = False
        try:
            container = docker_client.containers.get(node_info['container_id'])
            container_running = container.status == 'running'
        except:
            pass
        
        if not container_running:
            status = 'terminated'
            if node_info.get('status') != 'terminated':
                reschedule_pods_from_failed_node(node_id)
                node_info['status'] = 'terminated'
        elif (current_time - node_info['last_heartbeat']) > 30:
            status = 'unhealthy'
            if node_info.get('status') != 'unhealthy':
                node_info['status'] = 'unhealthy'
        else:
            status = 'healthy'
            node_info['status'] = 'healthy'
        
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


@app.route('/pods', methods=['POST'])
def launch_pod():
    global pod_id_counter
    data = request.json
    cpu_required = data.get('cpu_required', 1)
    algorithm = data.get('algorithm', SchedulingAlgorithm.FIRST_FIT.value)
    
    selected_node = select_node(cpu_required, algorithm)
    
    if not selected_node:
        return jsonify({
            'status': 'error',
            'message': 'No available nodes with sufficient resources'
        }), 400
    
    pod_id = f"pod-{pod_id_counter}"
    pods[pod_id] = {
        'cpu_required': cpu_required,
        'node_id': selected_node,
        'created_at': datetime.now().isoformat(),
        'status': 'running'
    }
    pod_id_counter += 1
    nodes[selected_node]['available_cpu'] -= cpu_required
    nodes[selected_node]['pods'].append(pod_id)
    
    return jsonify({
        'status': 'success',
        'message': 'Pod launched successfully',
        'pod_id': pod_id,
        'node_id': selected_node
    })

def reschedule_pods_from_failed_node(failed_node_id):
    """Reschedule pods from a failed node to other healthy nodes."""
    if failed_node_id not in nodes:
        return
    failed_node_pods = nodes[failed_node_id]['pods'].copy()  
    
    if not failed_node_pods:
        print(f"No pods to reschedule from failed node {failed_node_id}")
        return
    
    print(f"Attempting to reschedule {len(failed_node_pods)} pods from failed node {failed_node_id}")
    
    rescheduled_count = 0
    for pod_id in failed_node_pods:
        if pod_id not in pods:
            continue
            
        pod_info = pods[pod_id]
        
        if pod_info['status'] in ['rescheduled', 'failed']:
            continue
            
        cpu_required = pod_info['cpu_required']
        
        pod_info['status'] = 'rescheduling'
        print(f"Pod {pod_id} marked as rescheduling")
        
        new_node = select_node(cpu_required, SchedulingAlgorithm.FIRST_FIT.value)
        
        if new_node:
            if pod_id in nodes[failed_node_id]['pods']:
                nodes[failed_node_id]['pods'].remove(pod_id)
            
            pod_info['node_id'] = new_node
            pod_info['status'] = 'running'
            nodes[new_node]['pods'].append(pod_id)
            nodes[new_node]['available_cpu'] -= cpu_required
            rescheduled_count += 1
            print(f"Successfully rescheduled pod {pod_id} to node {new_node}")
        else:
            pod_info['status'] = 'failed'
            if pod_id in nodes[failed_node_id]['pods']:
                nodes[failed_node_id]['pods'].remove(pod_id)
            print(f"Could not reschedule pod {pod_id} - no available nodes")
    
    print(f"Rescheduled {rescheduled_count} pods from node {failed_node_id}")

@app.route('/pods', methods=['GET'])
def list_pods():
    pod_list = []
    for pod_id, pod_info in pods.items():
        node_id = pod_info['node_id']
        if node_id in nodes and nodes[node_id].get('status') == 'terminated' and pod_info['status'] == 'running':
            pod_info['status'] = 'rescheduling'
            reschedule_pods_from_failed_node(node_id)
            
        pod_list.append({
            'pod_id': pod_id,
            'cpu_required': pod_info['cpu_required'],
            'node_id': pod_info['node_id'],
            'status': pod_info['status'],
            'created_at': pod_info['created_at']
        })
    return jsonify({'pods': pod_list})

@app.route('/heartbeat/<node_id>', methods=['POST'])
def receive_heartbeat(node_id):
    if node_id not in nodes:
        return jsonify({'status': 'error', 'message': 'Node not found'}), 404
    
    nodes[node_id]['last_heartbeat'] = time.time()
    if nodes[node_id].get('status') != 'terminated':
        nodes[node_id]['status'] = 'healthy'
    return jsonify({'status': 'success'})

@app.route('/simulate/heartbeat/<node_id>', methods=['POST'])
def simulate_heartbeat(node_id):
    return receive_heartbeat(node_id)

def check_node_health():
    while True:
        current_time = time.time()
        
        for node_id, node_info in list(nodes.items()):
            try:
                container = docker_client.containers.get(node_info['container_id'])
                if container.status != 'running':
                    print(f"Container for node {node_id} is not running, status: {container.status}")
                    if node_info.get('status') != 'terminated':
                        reschedule_pods_from_failed_node(node_id)
                        node_info['status'] = 'terminated'
            except Exception as e:
                print(f"Container for node {node_id} not found: {str(e)}")
                if node_info.get('status') != 'terminated':
                    reschedule_pods_from_failed_node(node_id)
                    node_info['status'] = 'terminated'
        
        for node_id, node_info in nodes.items():
            if node_info.get('status') == 'terminated':
                continue
                
            if (current_time - node_info['last_heartbeat']) > 30:
                print(f"Node {node_id} missed heartbeat")
                node_info['status'] = 'unhealthy'
                reschedule_pods_from_failed_node(node_id)
        
        time.sleep(3)  

@app.route('/scheduling-algorithms', methods=['GET'])
def get_scheduling_algorithms():
    return jsonify({
        'algorithms': [alg.value for alg in SchedulingAlgorithm],
        'default': SchedulingAlgorithm.FIRST_FIT.value
    })

def simulate_automatic_heartbeats():
    while True:
        for node_id, node_info in list(nodes.items()):
            if node_info.get('status') == 'terminated':
                continue
                
            if random.random() < 0.9:
                node_info['last_heartbeat'] = time.time()
        
        time.sleep(random.uniform(5, 15))
heartbeat_thread = threading.Thread(target=simulate_automatic_heartbeats)
heartbeat_thread.daemon = True
heartbeat_thread.start()

health_thread = threading.Thread(target=check_node_health)
health_thread.daemon = True
health_thread.start()

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True)
