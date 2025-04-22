let autoRefreshInterval;
const AUTO_REFRESH_INTERVAL = 5000; // 5 seconds

document.addEventListener('DOMContentLoaded', function() {
    startAutoRefresh();
    loadSchedulingAlgorithms();

    document.getElementById('addNodeForm').addEventListener('submit', function(e) {
        e.preventDefault();
        const cpuCores = document.getElementById('cpuCores').value;
        
        fetch('/nodes', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
            },
            body: JSON.stringify({ cpu_cores: parseInt(cpuCores) })
        })
        .then(response => response.json())
        .then(data => {
            if (data.status === 'success') {
                alert(`Node added successfully: ${data.node_id}`);
                refreshAllData();
            } else {
                alert(`Error: ${data.message}`);
            }
        })
        .catch(error => {
            console.error('Error:', error);
            alert('Failed to add node');
        });
    });
    
    document.getElementById('refreshNodesBtn').addEventListener('click', refreshNodes);
    document.getElementById('refreshPodsBtn').addEventListener('click', refreshPods);
    
    document.getElementById('launchPodForm').addEventListener('submit', function(e) {
        e.preventDefault();
        const podCpu = document.getElementById('podCpu').value;
        const algorithm = document.getElementById('schedulingAlgorithm').value;
        const podStatus = document.getElementById('podStatus');
        podStatus.innerHTML = '<div class="spinner-border text-primary" role="status"><span class="visually-hidden">Loading...</span></div>';
        
        fetch('/pods', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
            },
            body: JSON.stringify({ 
                cpu_required: parseInt(podCpu),
                algorithm: algorithm
            })
        })
        .then(response => response.json())
        .then(data => {
            if (data.status === 'success') {
                podStatus.innerHTML = `
                    <div class="alert alert-success">
                        Pod launched successfully!<br>
                        Pod ID: ${data.pod_id}<br>
                        Assigned to Node: ${data.node_id}<br>
                        Algorithm: ${algorithm.replace('_', ' ')}
                    </div>
                `;
                refreshAllData();
            } else {
                podStatus.innerHTML = `
                    <div class="alert alert-danger">
                        Error: ${data.message}
                    </div>
                `;
            }
        })
        .catch(error => {
            console.error('Error:', error);
            podStatus.innerHTML = `
                <div class="alert alert-danger">
                    Failed to launch pod
                </div>
            `;
        });
    });
    
    document.getElementById('triggerHeartbeatBtn').addEventListener('click', function() {
        const nodeId = document.getElementById('heartbeatNodeSelect').value;
        if (!nodeId) return;
        
        fetch(`/simulate/heartbeat/${nodeId}`, {
            method: 'POST'
        })
        .then(response => response.json())
        .then(data => {
            if (data.status === 'success') {
                alert(`Heartbeat triggered for ${nodeId}`);
                refreshNodes();
            }
        })
        .catch(error => {
            console.error('Error:', error);
            alert('Failed to trigger heartbeat');
        });
    });
});

function refreshAllData() {
    refreshNodes();
    refreshPods();
}

function refreshNodes() {
    fetch('/nodes')
    .then(response => response.json())
    .then(data => {
        const nodesList = document.getElementById('nodesList');
        const heartbeatSelect = document.getElementById('heartbeatNodeSelect');
        
        nodesList.innerHTML = '';
        heartbeatSelect.innerHTML = '<option value="">Select node</option>';
        
        if (data.nodes.length === 0) {
            nodesList.innerHTML = '<p>No nodes in the cluster</p>';
            updateClusterVisualization([]);
            return;
        }
        
        const table = document.createElement('table');
        table.className = 'table table-striped';
        
        const thead = document.createElement('thead');
        thead.innerHTML = `
            <tr>
                <th>Node ID</th>
                <th>CPU</th>
                <th>Pods</th>
                <th>Status</th>
                <th>Container ID</th>
            </tr>
        `;
        table.appendChild(thead);
        
        // Table body
        const tbody = document.createElement('tbody');
        data.nodes.forEach(node => {
            const tr = document.createElement('tr');
            tr.innerHTML = `
                <td>${node.node_id}</td>
                <td>${node.available_cpu}/${node.cpu_cores}</td>
                <td>${node.pods_count}</td>
                <td>
                    <span class="badge ${node.status === 'healthy' ? 'bg-success' : 'bg-danger'}">
                        ${node.status}
                    </span>
                </td>
                <td class="text-truncate" style="max-width: 100px;">${node.container_id}</td>
            `;
            tbody.appendChild(tr);
            
            const option = document.createElement('option');
            option.value = node.node_id;
            option.textContent = node.node_id;
            heartbeatSelect.appendChild(option);
        });
        table.appendChild(tbody);
        
        nodesList.appendChild(table);
        updateClusterVisualization(data.nodes);
    })
    .catch(error => {
        console.error('Error:', error);
        alert('Failed to fetch nodes');
    });
}

function refreshPods() {
    fetch('/pods')
    .then(response => response.json())
    .then(data => {
        const podStatus = document.getElementById('podStatus');
        
        if (data.pods.length === 0) {
            podStatus.innerHTML = '<div class="alert alert-info">No pods in the cluster</div>';
            return;
        }
        
        const table = document.createElement('table');
        table.className = 'table table-striped';
        
        const thead = document.createElement('thead');
        thead.innerHTML = `
            <tr>
                <th>Pod ID</th>
                <th>CPU</th>
                <th>Node</th>
                <th>Status</th>
                <th>Created At</th>
            </tr>
        `;
        table.appendChild(thead);
        
        const tbody = document.createElement('tbody');
        data.pods.forEach(pod => {
            const tr = document.createElement('tr');
            
            let badgeClass = '';
            if (pod.status === 'running') {
                badgeClass = 'bg-success';
            } else if (pod.status === 'rescheduling') {
                badgeClass = 'bg-warning';
            } else if (pod.status === 'failed') {
                badgeClass = 'bg-danger';
            } else if (pod.status === 'terminated') {
                badgeClass = 'bg-secondary';
            } else {
                badgeClass = 'bg-info';
            }
            
            tr.innerHTML = `
                <td>${pod.pod_id}</td>
                <td>${pod.cpu_required}</td>
                <td>${pod.node_id}</td>
                <td>
                    <span class="badge ${badgeClass}">
                        ${pod.status}
                    </span>
                </td>
                <td>${new Date(pod.created_at).toLocaleTimeString()}</td>
            `;
            tbody.appendChild(tr);
        });
        table.appendChild(tbody);
        
        podStatus.innerHTML = '';
        podStatus.appendChild(table);
    })
    .catch(error => {
        console.error('Error:', error);
        alert('Failed to fetch pods');
    });
}

function updateClusterVisualization(nodes) {
    const visualization = document.getElementById('clusterVisualization');
    
    if (nodes.length === 0) {
        visualization.innerHTML = `
            <div class="text-center py-4 text-muted">
                <i class="bi bi-diagram-3 fs-1"></i>
                <p class="mt-2">No nodes in cluster</p>
            </div>
        `;
        return;
    }
    
    let html = '<div class="cluster-nodes">';
    
    nodes.forEach(node => {
        const usedCpu = node.cpu_cores - node.available_cpu;
        const cpuPercentage = (usedCpu / node.cpu_cores) * 100;
        let borderClass = '';
        if (node.status === 'terminated') {
            borderClass = 'node-terminated';
        } else if (node.status === 'healthy') {
            borderClass = 'node-healthy';
        } else {
            borderClass = 'node-unhealthy';
        }
        
        html += `
            <div class="cluster-node ${borderClass}">
                <div class="node-header">
                    <h6>${node.node_id}</h6>
                    <span class="badge ${node.status === 'healthy' ? 'bg-success' : 
                                      node.status === 'unhealthy' ? 'bg-danger' : 'bg-secondary'}">
                        ${node.status}
                    </span>
                </div>
                ${node.status === 'terminated' ? `
                <div class="alert alert-warning py-1 my-1">
                    <small>Container terminated</small>
                </div>
                ` : ''}
                <div class="node-resources">
                    <div class="resource-bar">
                        <div class="resource-usage" style="width: ${cpuPercentage}%"></div>
                    </div>
                    <small>CPU: ${usedCpu}/${node.cpu_cores} cores</small>
                </div>
                <div class="node-pods">
                    ${node.pods.length > 0 ? 
                        node.pods.map(podId => `
                            <div class="pod" title="Pod ${podId}">
                                <i class="bi bi-box"></i>
                            </div>
                        `).join('') : 
                        '<div class="text-muted">No pods</div>'
                    }
                </div>
            </div>
        `;
    });
    
    html += '</div>';
    visualization.innerHTML = html;
}


function startAutoRefresh() {
    refreshAllData();
    autoRefreshInterval = setInterval(refreshAllData, AUTO_REFRESH_INTERVAL);
    document.addEventListener('visibilitychange', function() {
        if (document.hidden) {
            clearInterval(autoRefreshInterval);
        } else {
            refreshAllData();
            autoRefreshInterval = setInterval(refreshAllData, AUTO_REFRESH_INTERVAL);
        }
    });
}

function loadSchedulingAlgorithms() {
    fetch('/scheduling-algorithms')
    .then(response => response.json())
    .then(data => {
        const select = document.getElementById('schedulingAlgorithm');
        select.innerHTML = '';
        
        data.algorithms.forEach(alg => {
            const option = document.createElement('option');
            option.value = alg;
            option.textContent = alg.replace('_', ' ');
            if (alg === data.default) {
                option.selected = true;
            }
            select.appendChild(option);
        });
    })
    .catch(error => {
        console.error('Error loading scheduling algorithms:', error);
    });
}
