import React, { useState, useRef, useEffect } from 'react';
import { X, MessageSquare, Send, ChevronRight, ChevronLeft, Loader2 } from 'lucide-react';

function Chatbot({ isOpen, setIsOpen, user }) {
  const [message, setMessage] = useState('');
  const [messages, setMessages] = useState([
    {
      type: 'bot',
      text: 'Hi! I\'m **BullRun**, your investment assistant. I can help you understand your portfolio, analyze market conditions, and answer questions about your holdings. How can I help you today?',
      time: new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })
    }
  ]);
  
  const messagesEndRef = useRef(null);
  const messagesContainerRef = useRef(null);

  // Auto-scroll to bottom when messages change
  const scrollToBottom = () => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  };

  useEffect(() => {
    scrollToBottom();
  }, [messages]);

  const handleSendMessage = async () => {
    if (!message.trim()) return;

    const newMessage = {
      type: 'user',
      text: message,
      time: new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })
    };

    setMessages(prev => [...prev, newMessage]);
    const currentMessage = message;
    setMessage('');

    const token = user?.token;
    if (!token) {
      // Handle not logged in
      return;
    }

    // Show loading indicator
    const loadingMessage = {
      id: Date.now(),
      type: 'bot',
      text: 'BullRun is thinking...',
      time: new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }),
      isTyping: true,
    };
    setMessages(prev => [...prev, loadingMessage]);

    try {
      const API_BASE_URL = import.meta.env.VITE_API_BASE_URL || 'http://localhost:5000';
      const response = await fetch(`${API_BASE_URL}/api/chatbot/query`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'Authorization': `Bearer ${token}`
        },
        body: JSON.stringify({ message: currentMessage })
      });

      const data = await response.json();

      // Remove loading indicator and add final response
      setMessages(prev => {
        const newMessages = prev.filter(msg => !msg.isTyping);
        newMessages.push({
          type: 'bot',
          text: data.response || "Sorry, something went wrong.",
          time: new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })
        });
        return newMessages;
      });

    } catch (error) {
      console.error('Chatbot error:', error);
      // Remove loading and show error
       setMessages(prev => {
        const newMessages = prev.filter(msg => !msg.isTyping);
        newMessages.push({
          type: 'bot',
          text: "Sorry, I'm having trouble connecting.",
          time: new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })
        });
        return newMessages;
      });
    }
  };

  // Loading spinner component
  const LoadingSpinner = () => (
    <div className="flex items-center gap-2">
      <Loader2 className="w-3 h-3 animate-spin text-green-600" />
      <span className="text-xs text-gray-500">BullRun is thinking...</span>
    </div>
  );

  return (
    <>
      {/* MOBILE: CLOSED TAB */}
      {!isOpen && (
        <div className="md:hidden fixed right-0 top-[68%] translate-y-0 z-40">
          <button
            onClick={() => setIsOpen(true)}
            className="px-2 py-4 bg-white border border-gray-200 rounded-l-2xl shadow hover:bg-gray-50 active:scale-[0.98] transition cursor-pointer animate-nudge-slow"
            title="Open Chat"
            aria-label="Open chat"
          >
            <MessageSquare className="w-5 h-5 text-green-600" />
          </button>
        </div>
      )}

      {/* MOBILE: OPEN OVERLAY */}
      {isOpen && (
        <div className="md:hidden fixed inset-0 z-50 bg-white border-l border-gray-200 flex flex-col animate-slide-in-right">
          {/* Header */}
          <div className="px-4 py-3 border-b border-gray-200">
            <div className="flex items-center justify-between gap-2.5">
              <div className="flex items-center gap-2.5">
                <div className="w-9 h-9 bg-gradient-to-br from-green-400 to-green-600 rounded-md flex items-center justify-center flex-shrink-0">
                  <MessageSquare className="w-4 h-4 text-white" />
                </div>
                <div className="min-w-0">
                  <h3 className="font-bold text-gray-900 text-xs">Chat with BullRun</h3>
                  <p className="text-[10px] text-gray-500 leading-tight">Your AI investment assistant</p>
                </div>
              </div>
              <div className="flex items-center gap-0.5">
                <button
                  onClick={() => setIsOpen(false)}
                  className="p-1 text-gray-400 hover:text-gray-600 hover:bg-gray-100 rounded transition-colors cursor-pointer"
                  title="Collapse"
                  aria-label="Collapse chat"
                >
                  <ChevronRight className="w-3.5 h-3.5" />
                </button>
              </div>
            </div>
          </div>

          {/* Messages */}
          <div ref={messagesContainerRef} className="flex-1 overflow-y-auto p-3 space-y-3">
            {messages.map((msg, index) => (
              <div key={index} className={`flex ${msg.type === 'user' ? 'justify-end' : 'justify-start'}`}>
                <div className={`max-w-[85%] ${msg.type === 'user' ? 'order-2' : 'order-1'}`}>
                  {msg.type === 'bot' && !msg.isTyping && (
                    <div className="flex items-center gap-1.5 mb-1">
                      <div className="w-5 h-5 bg-green-600 rounded-full flex items-center justify-center">
                        <span className="text-white text-[8px] font-bold">BR</span>
                      </div>
                        <span className="text-[10px] font-medium text-gray-700">BullRun</span>
                    </div>
                  )}
                  <div className={`px-3 py-2 rounded-lg ${msg.type === 'user'
                      ? 'bg-green-600 text-white ml-auto'
                      : 'bg-gray-100 text-gray-800'
                    }`}>
                    {msg.isTyping ? (
                      <LoadingSpinner />
                    ) : (
                      <p className="text-xs leading-relaxed"
                         dangerouslySetInnerHTML={{ 
                            __html: msg.text
                              .replace(/\*\*(.*?)\*\*/g, '<strong>$1</strong>')
                              .replace(/\*(.*?)\*/g, '<em>$1</em>')
                              .replace(/`(.*?)`/g, '<code class="bg-gray-200 px-1 py-0.5 rounded text-xs">$1</code>')
                              .replace(/\n/g, '<br />')
                          }}
                      />
                    )}
                  </div>
                  <p className="text-[9px] text-gray-400 mt-0.5 px-1">{msg.time}</p>
                </div>
              </div>
            ))}
            <div ref={messagesEndRef} />
          </div>

          {/* Input */}
          <div className="p-3 border-t border-gray-200">
            <div className="flex gap-1.5">
              <input
                type="text"
                value={message}
                onChange={(e) => setMessage(e.target.value)}
                onKeyDown={(e) => e.key === 'Enter' && handleSendMessage()}
                placeholder="Ask me anything"
                className="flex-1 px-3 py-2 text-xs border border-gray-200 rounded-md focus:outline-none focus:ring-1 focus:ring-green-600 focus:border-transparent"
              />
              <button
                onClick={handleSendMessage}
                className="p-2 bg-green-600 text-white rounded-md hover:bg-green-700 transition-colors flex items-center justify-center cursor-pointer"
              >
                <Send className="w-4 h-4" />
              </button>
            </div>
          </div>
        </div>
      )}

      {/* DESKTOP: PERSISTENT CONTAINER WITH WIDTH TRANSITION */}
      <div className={`hidden md:flex bg-white border-l border-gray-200 h-full flex-col transition-all duration-300 ease-out ${isOpen ? 'w-[380px]' : 'w-12'}`}>
        {isOpen ? (
          <>
            {/* Header (open) */}
            <div className="px-4 py-3 border-b border-gray-200">
              <div className="flex items-center justify-between gap-2.5">
                <div className="flex items-center gap-2.5">
                  <div className="w-9 h-9 bg-gradient-to-br from-green-400 to-green-600 rounded-md flex items-center justify-center flex-shrink-0">
                    <MessageSquare className="w-4 h-4 text-white" />
                  </div>
                  <div className="min-w-0">
                    <h3 className="font-bold text-gray-900 text-xs">Chat with BullRun</h3>
                    <p className="text-[10px] text-gray-500 leading-tight">Discuss investments and manage your strategies</p>
                  </div>
                </div>
                <div className="flex items-center gap-0.5">
                  <button
                    onClick={() => setIsOpen(false)}
                    className="p-1 text-gray-400 hover:text-gray-600 hover:bg-gray-100 rounded transition-colors cursor-pointer"
                    title="Collapse"
                    aria-label="Collapse chat"
                  >
                    <ChevronRight className="w-3.5 h-3.5" />
                  </button>
                </div>
              </div>
            </div>

            {/* Messages */}
            <div ref={messagesContainerRef} className="flex-1 overflow-y-auto p-3 space-y-3">
              {messages.map((msg, index) => (
                <div key={index} className={`flex ${msg.type === 'user' ? 'justify-end' : 'justify-start'}`}>
                  <div className={`max-w-[85%] ${msg.type === 'user' ? 'order-2' : 'order-1'}`}>
                    {msg.type === 'bot' && !msg.isTyping && (
                      <div className="flex items-center gap-1.5 mb-1">
                        <div className="w-5 h-5 bg-green-600 rounded-full flex items-center justify-center">
                          <span className="text-white text-[8px] font-bold">BR</span>
                        </div>
                        <span className="text-[10px] text-gray-700 font-medium">BullRun</span>
                      </div>
                    )}
                    <div className={`px-3 py-2 rounded-lg ${msg.type === 'user'
                        ? 'bg-green-600 text-white ml-auto'
                        : 'bg-gray-100 text-gray-800'
                      }`}>
                      {msg.isTyping ? (
                        <LoadingSpinner />
                      ) : (
                        <p className="text-xs leading-relaxed"
                           dangerouslySetInnerHTML={{ 
                            __html: msg.text
                              .replace(/\*\*(.*?)\*\*/g, '<strong>$1</strong>')
                              .replace(/\*(.*?)\*/g, '<em>$1</em>')
                              .replace(/`(.*?)`/g, '<code class="bg-gray-200 px-1 py-0.5 rounded text-xs">$1</code>')
                              .replace(/\n/g, '<br />')
                          }}
                        />
                      )}
                    </div>
                    <p className="text-[9px] text-gray-400 mt-0.5 px-1">{msg.time}</p>
                  </div>
                </div>
              ))}
              <div ref={messagesEndRef} />
            </div>

            {/* Input */}
            <div className="p-3 border-t border-gray-200">
              <div className="flex gap-1.5">
                <input
                  type="text"
                  value={message}
                  onChange={(e) => setMessage(e.target.value)}
                  onKeyDown={(e) => e.key === 'Enter' && handleSendMessage()}
                  placeholder="Ask me anything"
                  className="flex-1 px-3 py-2 text-xs border border-gray-200 rounded-md focus:outline-none focus:ring-1 focus:ring-green-600 focus:border-transparent"
                />
                <button
                  onClick={handleSendMessage}
                  className="p-2 bg-green-600 text-white rounded-md hover:bg-green-700 transition-colors flex items-center justify-center cursor-pointer"
                >
                  <Send className="w-4 h-4" />
                </button>
              </div>
            </div>
          </>
        ) : (
          /* Collapsed rail: show only an open button, no avatar */
          <div className="flex-1 flex items-start justify-center pt-4">
            <button
              onClick={() => setIsOpen(true)}
              className="p-2 text-gray-600 hover:text-gray-900 hover:bg-gray-100 rounded transition-colors cursor-pointer"
              title="Open Chat"
              aria-label="Open chat"
            >
              <ChevronLeft className="w-4 h-4" />
            </button>
          </div>
        )}
      </div>
    </>
  );
}

export default Chatbot;