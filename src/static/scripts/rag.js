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

    // Use safer querySelector instead of getElementById
    const chatContainer1 = document.querySelector('#chat-output-without-rag');
    const chatContainer2 = document.querySelector('#chat-output-with-rag');
    const userInput = document.querySelector('#user-input');

    async function appendToChat(message, containerId) {
        const container = document.querySelector('#' + containerId);
        container.value += message;
        container.scrollTop = container.scrollHeight;
    }

    async function streamResponse(message, botId, containerId) {
        try {
            let use_rag_param = false;

            if (botId == 2) {
                use_rag_param = true;
            }

            const response = await fetch('/stream', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                    'X-CSRFToken': csrfToken
                },
                body: stableJSONStringify({
                    message: message,
                    bot_id: botId,
                    use_rag: use_rag_param
                })
            });

            const container = document.querySelector('#' + containerId);
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
                            const data = JSON.parse(line.slice(6));
                            if (data.content) {
                                appendToChat(data.content, containerId);
                            }
                            if (data.timings) {
                                const metrics = data.timings;
                                const metricsId = 'metrics' + botId;
                                const metricsDiv = document.querySelector('#' + metricsId);
                                const PredictionInSeconds = (metrics.predicted_ms / 1000).toFixed(2);

                                // Create the metrics content using textContent or createElement
                                const metricsContent = document.createElement('div');

                                // Create and append elements safely
                                const latencySpan = document.createElement('span');
                                latencySpan.textContent = 'Latency: ' + metrics.predicted_per_token_ms.toFixed(2) + ' ms | Throughput: ' + metrics.predicted_per_second.toFixed(2);
                                metricsContent.appendChild(latencySpan);

                                metricsContent.appendChild(document.createElement('br'));

                                const tokensSpan = document.createElement('span');
                                tokensSpan.textContent = 'Output tokens: ' + metrics.predicted_n;
                                metricsContent.appendChild(tokensSpan);

                                metricsContent.appendChild(document.createElement('br'));

                                const predictionSpan = document.createElement('span');
                                predictionSpan.textContent = 'Prediction time: ' + PredictionInSeconds + ' seconds';
                                metricsContent.appendChild(predictionSpan);

                                // Clear previous content and append new content
                                while (metricsDiv.firstChild) {
                                    metricsDiv.removeChild(metricsDiv.firstChild);
                                }
                                metricsDiv.appendChild(metricsContent);

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
            appendToChat('You: ' + message + '\n', 'chat-output-without-rag');
            appendToChat('You: ' + message + '\n', 'chat-output-with-rag');

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
        const metrics1 = document.querySelector('#metrics1');
        const metrics2 = document.querySelector('#metrics2');
        while (metrics1.firstChild) metrics1.removeChild(metrics1.firstChild);
        while (metrics2.firstChild) metrics2.removeChild(metrics2.firstChild);
    }

    // Event Listeners
    const sendButton = document.querySelector('#send-button');
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

    document.querySelector('#clear-button').addEventListener('click', clearChat);
});