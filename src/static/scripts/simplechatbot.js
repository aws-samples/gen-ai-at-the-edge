// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: MIT-0
function updateMetrics(data, PredictionTime) {
    const metricsDiv = document.getElementById('metrics');
    metricsDiv.textContent = ''; // Clear existing content

    const createMetricLine = (content) => {
        const strong = document.createElement('strong');
        strong.textContent = content;
        return strong;
    };

    const line1 = createMetricLine("Latency: " + data.timings.predicted_per_token_ms.toFixed(2) + " (ms) | Throughput: " + data.timings.predicted_per_second.toFixed(2));
    const line2 = createMetricLine("Output tokens: " + data.timings.predicted_n);
    const line3 = createMetricLine("Prediction time: " + PredictionTime + " seconds");

    metricsDiv.appendChild(line1);
    metricsDiv.appendChild(document.createElement('br'));
    metricsDiv.appendChild(line2);
    metricsDiv.appendChild(document.createElement('br'));
    metricsDiv.appendChild(line3);
}

function stableJSONStringify(obj) {
    if (typeof JSONStringify !== 'undefined') {
        return JSONStringify(obj);
    }
    // Fallback implementation if the library isn't loaded
    const allKeys = [];
    JSON.stringify(obj, (key, value) => {
        if (key) allKeys.push(key);
        return value;
    });
    allKeys.sort();
    return JSON.stringify(obj, allKeys);
}

async function generate() {
    const prompt = document.getElementById('user-input').value;
    const output = document.getElementById('chat-output');
    const metricsDiv = document.getElementById('metrics');
    const selectedModel = document.getElementById('model-select').value;
    const csrfToken = document.querySelector('meta[name="csrf-token"]').getAttribute('content');

    output.value += `You: ${prompt}\n\n${selectedModel}: `;
    metricsDiv.innerHTML = '';

    try {
        const response = await fetch('/generate', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
                'X-CSRFToken': csrfToken
            },
            body: stableJSONStringify({
                prompt,
                model: selectedModel
            }),
        });

        const reader = response.body.getReader();
        const decoder = new TextDecoder();
        let buffer = '';

        while (true) {
            const { value, done } = await reader.read();

            buffer += decoder.decode(value, { stream: true });
            const lines = buffer.split('\n');

            for (const line of lines) {
                if (line.trim().startsWith('data:')) {
                    try {
                        const jsonStr = line.trim().substring(5);
                        const data = JSON.parse(jsonStr);

                        if (data.content) {
                            output.value += data.content;
                        }

                        if (data.stop) {
                            output.value += "\n";
                            const PredictionTime = (data.timings.predicted_ms/1000).toFixed(2);
                            updateMetrics(data, PredictionTime);
                            output.scrollTop = output.scrollHeight;

                            return;
                        }
                    } catch (error) {
                        console.error('Error: ', error);
                        console.error('Json: ', line.trim().substring(5))
                    }
                }
            }
            buffer = lines[lines.length - 1];
            output.scrollTop = output.scrollHeight;

            if (done) break;
        }
    } catch (error) {
        console.error('Error:', error);
        output.value += 'An error occurred while generating text.\n\n';
    }
}

function clearChat() {
    const prompt = document.getElementById('user-input');
    const output = document.getElementById('chat-output');
    const metricsDiv = document.getElementById('metrics');

    prompt.value = '';
    output.value = '';
    metricsDiv.innerHTML = '';
}
