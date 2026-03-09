const chatbotResponses = {
    sleep: 'Getting quality sleep is essential for preventing burnout. Aim for 7-9 hours per night. Try to maintain a consistent sleep schedule and avoid screens 30 minutes before bed.',
    stress: 'To manage stress, try deep breathing exercises, meditation, yoga, or progressive muscle relaxation. Regular exercise and spending time in nature also help significantly.',
    exercise: 'Exercise is great for reducing burnout. Aim for at least 30 minutes of moderate activity like walking, running, or cycling most days of the week.',
    burnout: 'Burnout is a state of emotional, physical, and mental exhaustion. If you are experiencing burnout, consider taking breaks, setting work boundaries, and talking to a mental health professional.',
    rest: 'Rest and recovery are crucial. Make sure to take regular breaks during work, use your vacation days, and engage in activities you enjoy outside of work.',
    'mental health': 'Your mental health is important. If you are struggling, please reach out to a counselor, therapist, or mental health professional. There is no shame in seeking help.',
    'work-life balance': 'Work-life balance is essential. Set clear boundaries between work and personal time, delegate when possible, and prioritize activities that bring you joy.',
    breathing: 'Try the 4-7-8 breathing technique: inhale for 4 counts, hold for 7, exhale for 8. This helps calm your nervous system and reduce anxiety.',
    meditation: 'Meditation is excellent for managing stress. Start with just 5-10 minutes daily. Apps like Headspace or Calm can guide you.',
    'exercise habits': 'Build exercise into your routine gradually. Even a 10-minute walk can help. Find an activity you enjoy to make it sustainable.',
};

const defaultResponses = [
    'That is an interesting question about wellness. Can I help with something specific about sleep, stress, exercise, or burnout?',
    'I am here to help with wellness topics. Try asking me about sleep, stress management, exercise, or burnout.',
    'I am a wellness chatbot. I can provide advice on stress, sleep, exercise, and preventing burnout. What would you like to know?',
];

function getBotResponse(userMessage) {
    const lowerMessage = userMessage.toLowerCase();

    for (const [keyword, response] of Object.entries(chatbotResponses)) {
        if (lowerMessage.includes(keyword)) {
            return response;
        }
    }

    return defaultResponses[Math.floor(Math.random() * defaultResponses.length)];
}

window.initChatbot = function initChatbot() {
    const chatInput = document.getElementById('chatInput');
    const chatSendBtn = document.getElementById('chatSendBtn');
    const chatHistory = document.getElementById('chatHistory');

    if (!chatInput || !chatSendBtn || !chatHistory) {
        return;
    }

    function addMessage(text, isUser) {
        const messageDiv = document.createElement('div');
        messageDiv.className = `chat-message ${isUser ? 'message-user' : 'message-bot'}`;

        const contentDiv = document.createElement('div');
        contentDiv.className = 'message-content';
        contentDiv.textContent = text;

        messageDiv.appendChild(contentDiv);
        chatHistory.appendChild(messageDiv);
        chatHistory.scrollTop = chatHistory.scrollHeight;
    }

    function sendChatMessage() {
        const message = chatInput.value.trim();
        if (message === '') {
            return;
        }

        addMessage(message, true);
        chatInput.value = '';

        setTimeout(() => {
            addMessage(getBotResponse(message), false);
        }, 500);
    }

    chatSendBtn.onclick = sendChatMessage;
    chatInput.onkeypress = (event) => {
        if (event.key === 'Enter') {
            sendChatMessage();
        }
    };

    if (chatHistory.children.length === 0) {
        addMessage('Hello. I am your wellness assistant. Ask me anything about sleep, stress, exercise, preventing burnout, or general wellness tips.', false);
    }
};
