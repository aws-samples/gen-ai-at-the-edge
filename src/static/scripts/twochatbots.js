// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: MIT-0
$(document).ready(function() {
    const csrfToken = document.querySelector('meta[name="csrf-token"]').getAttribute('content');
    // Utility function for stable JSON stringification
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

    const chatContainer1 = document.getElementById('chat-output-without-rag');
    const chatContainer2 = document.getElementById('chat-output-with-rag');
    const userInput = document.getElementById('user-input');

    async function appendToChat(message, containerId) {
        const container = document.getElementById(containerId);
        container.value += message;
        container.scrollTop = container.scrollHeight;
    }

    async function updateMetrics(metrics, botId) {
        const metricsId = 'metrics' + botId;
        const metricsDiv = document.getElementById(metricsId);
        const PredictionInSeconds = (metrics.predicted_ms / 1000).toFixed(2);

        // Clear previous content
        metricsDiv.textContent = '';

        // Create and append elements safely
        const line1 = document.createElement('div');
        line1.textContent = "Latency: " + metrics.predicted_per_token_ms.toFixed(2) + " ms | Throughput: " + metrics.predicted_per_second.toFixed(2);

        const line2 = document.createElement('div');
        line2.textContent = "Output tokens: " + metrics.predicted_n;

        const line3 = document.createElement('div');
        line3.textContent = "Prediction time: "  + PredictionInSeconds + " seconds";

        metricsDiv.appendChild(line1);
        metricsDiv.appendChild(line2);
        metricsDiv.appendChild(line3);
    }

    async function streamResponse(message, botId, containerId) {
        try {
            // Use JSONStringify for stable key ordering
            const payload = stableJSONStringify({
                message: message,
                bot_id: botId
            });

            const response = await fetch('/stream', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                    'X-CSRFToken': csrfToken
                },
                body: payload
            });

            const container = document.getElementById(containerId);
            const reader = response.body.getReader();
            const decoder = new TextDecoder();
            let buffer = '';

            while (true) {
                const { value, done } = await reader.read();

                buffer += decoder.decode(value, { stream: true });
                const lines = buffer.split('\n');

                for (let i = 0; i < lines.length - 1; i++) {
                    const line = lines[i].trim();
                    if (line.startsWith('data: ')) {
                        try {
                            // Parse the incoming JSON data
                            const jsonStr = line.slice(6);
                            const data = JSON.parse(jsonStr);

                            if (data.content) {
                                appendToChat(data.content, containerId);
                            }
                            if (data.timings) {
                                updateMetrics(data.timings, botId);
                                container.scrollTop = container.scrollHeight;
                                return;
                            }
                        } catch (e) {
                            console.error('Error parsing JSON:', e);
                        }
                    }
                }
                buffer = lines[lines.length - 1];

                if (done) break;
            }
        } catch (error) {
            console.error('Stream error:', error);
            appendToChat('\nError: Failed to get response\n', containerId);
        }
    }

    async function sendMessage() {
        const message = userInput.value.trim();
        if (message) {
            // Clear previous responses
            chatContainer1.value = '';
            chatContainer2.value = '';

            // Add user message to both chats
            appendToChat("You: " + message + "\n", 'chat-output-without-rag');
            appendToChat("You: " + message + "\n", 'chat-output-with-rag');

            // Create both stream promises
            const stream1 = streamResponse(message, 1, 'chat-output-without-rag');
            const stream2 = streamResponse(message, 2, 'chat-output-with-rag');

            // Execute both streams in parallel and handle errors independently
            try {
                await Promise.allSettled([stream1, stream2]);
            } catch (error) {
                console.error('Error in parallel execution:', error);
            }

            userInput.value = '';
        }
    }

    function clearChat() {
        chatContainer1.value = '';
        chatContainer2.value = '';
        userInput.value = '';
        document.getElementById('metrics1').textContent = '';
        document.getElementById('metrics2').textContent = '';
    }

    // Event Listeners
    const sendButton = document.getElementById('send-button');
    sendButton.addEventListener('click', async () => {
        sendButton.disabled = true;
        await sendMessage();
        sendButton.disabled = false;
    });

    userInput.addEventListener('keypress', async function(e) {
        if (e.key === 'Enter') {
            sendButton.disabled = true;
            await sendMessage();
            sendButton.disabled = false;
        }
    });

    document.getElementById('clear-button').addEventListener('click', clearChat);
});