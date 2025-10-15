import React, { useState } from 'react';
import { X, MessageSquare, Send, ChevronRight, ChevronLeft } from 'lucide-react';

function Chatbot({ isOpen, setIsOpen }) {
  const [message, setMessage] = useState('');
  const [messages, setMessages] = useState([
    {
      type: 'bot',
      text: 'Hi! I\'m BullRun, your investment assistant. How can I help you today?',
      time: new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })
    }
  ]);

  const handleSendMessage = () => {
    if (!message.trim()) return;

    const newMessage = {
      type: 'user',
      text: message,
      time: new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })
    };

    setMessages([...messages, newMessage]);
    setMessage('');

    setTimeout(() => {
      const botResponse = {
        type: 'bot',
        text: 'I\'m analyzing your request. This is a demo response. In production, I would provide detailed market insights and investment recommendations.',
        time: new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })
      };
      setMessages(prev => [...prev, botResponse]);
    }, 1000);
  };

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
          <div className="flex-1 overflow-y-auto p-3 space-y-3">
            {messages.map((msg, index) => (
              <div key={index} className={`flex ${msg.type === 'user' ? 'justify-end' : 'justify-start'}`}>
                <div className={`max-w-[85%] ${msg.type === 'user' ? 'order-2' : 'order-1'}`}>
                  {msg.type === 'bot' && (
                    <div className="flex items-center gap-1.5 mb-1">
                      <div className="w-5 h-5 bg-green-600 rounded-full flex items-center justify-center">
                        <span className="text-white text-[8px] font-bold">BR</span>
                      </div>
                      <span className="text-[10px] font-medium text-gray-700">BullRun</span>
                    </div>
                  )}
                  <div className={`px-3 py-2 rounded-lg ${
                    msg.type === 'user' 
                      ? 'bg-green-600 text-white ml-auto' 
                      : 'bg-gray-100 text-gray-800'
                  }`}>
                    <p className="text-xs leading-relaxed">{msg.text}</p>
                  </div>
                  <p className="text-[9px] text-gray-400 mt-0.5 px-1">{msg.time}</p>
                </div>
              </div>
            ))}
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
            <div className="flex-1 overflow-y-auto p-3 space-y-3">
              {messages.map((msg, index) => (
                <div key={index} className={`flex ${msg.type === 'user' ? 'justify-end' : 'justify-start'}`}>
                  <div className={`max-w-[85%] ${msg.type === 'user' ? 'order-2' : 'order-1'}`}>
                    {msg.type === 'bot' && (
                      <div className="flex items-center gap-1.5 mb-1">
                        <div className="w-5 h-5 bg-green-600 rounded-full flex items-center justify-center">
                          <span className="text-white text-[8px] font-bold">BR</span>
                        </div>
                        <span className="text-[10px] text-gray-700 font-medium">BullRun</span>
                      </div>
                    )}
                    <div className={`px-3 py-2 rounded-lg ${
                      msg.type === 'user' 
                        ? 'bg-green-600 text-white ml-auto' 
                        : 'bg-gray-100 text-gray-800'
                    }`}>
                      <p className="text-xs leading-relaxed">{msg.text}</p>
                    </div>
                    <p className="text-[9px] text-gray-400 mt-0.5 px-1">{msg.time}</p>
                  </div>
                </div>
              ))}
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