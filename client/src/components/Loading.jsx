import React from 'react';
import bullrunLogo from '../assets/br.png';

function Loading({ message = 'Loading...', fullScreen = true }) {
  const containerClasses = fullScreen
    ? 'fixed inset-0 bg-gray-50 flex items-center justify-center z-50'
    : 'w-full h-full flex items-center justify-center bg-gray-50';

  return (
    <div className={containerClasses}>
      <div className="flex flex-col items-center gap-4">
        {/* Animated BR Logo */}
        <div className="relative">
          {/* Outer spinning ring */}
          <div className="absolute inset-0 w-16 h-16 rounded-full border-4 border-gray-200" />
          <div className="absolute inset-0 w-16 h-16 rounded-full border-4 border-transparent border-t-green-500 border-r-green-500 animate-spin" />
          
          {/* Logo in center */}
          <div className="relative w-16 h-16 rounded-full bg-white flex items-center justify-center shadow-sm">
            <img 
              src={bullrunLogo} 
              alt="BullRun" 
              className="w-10 h-10 animate-pulse" 
            />
          </div>
        </div>

        {/* Loading text */}
        <div className="flex flex-col items-center gap-2">
          <p className="text-sm font-medium text-gray-700">{message}</p>
          <div className="flex gap-1">
            <span className="w-2 h-2 bg-green-500 rounded-full animate-bounce" style={{ animationDelay: '0ms' }} />
            <span className="w-2 h-2 bg-green-500 rounded-full animate-bounce" style={{ animationDelay: '150ms' }} />
            <span className="w-2 h-2 bg-green-500 rounded-full animate-bounce" style={{ animationDelay: '300ms' }} />
          </div>
        </div>
      </div>
    </div>
  );
}

export default Loading;

