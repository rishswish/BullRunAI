import { BrowserRouter as Router, Routes, Route, Navigate, useLocation } from 'react-router-dom';
import { useState, useEffect, useRef } from 'react';
import { GoogleOAuthProvider } from '@react-oauth/google';
import Dashboard from './pages/Dashboard';
import Portfolio from './pages/Portfolio';
import Login from './pages/Login';
import Onboarding from './pages/Onboarding';
import Navbar from './components/Navbar';
import Chatbot from './components/Chatbot';
import Loading from './components/Loading';
import Ticker from './pages/Ticker';
import './app.css';

const VITE_APP_GOOGLE_CLIENT_ID = import.meta.env.VITE_APP_GOOGLE_CLIENT_ID;
const VITE_APP_API_URL = import.meta.env.VITE_APP_API_URL;

function AppContent({ user, profile, checkingProfile, updateProfile, handleLogout, theme, setTheme }) {
  const isMobile = () => {
    if (typeof window === 'undefined') return false;
    return window.matchMedia('(max-width: 768px)').matches
      || /Mobi|Android|iPhone|iPad|iPod/i.test(navigator.userAgent);
  };

  const [isChatbotOpen, setIsChatbotOpen] = useState(() => !isMobile());
  const location = useLocation();
  const isOnboarding = location.pathname === '/onboarding';

  return (
    <div className="w-full h-full flex flex-col">
      <Navbar onLogout={handleLogout} user={user} theme={theme} onThemeChange={setTheme} />
      <div className="flex-1 overflow-hidden flex">
        <div className="flex-1 overflow-auto">
          <Routes>
            <Route
              path="/"
              element={
                checkingProfile
                  ? <Loading message="Preparing your workspace..." />
                  : (profile
                    ? (profile.hasUserOnboarded ? <Navigate to="/dashboard" replace /> : <Navigate to="/onboarding" replace />)
                    : <Loading message="Preparing your workspace..." />)
              }
            />
            <Route
              path="/onboarding"
              element={
                checkingProfile
                  ? <Loading message="Preparing onboarding..." />
                  : (profile && profile.hasUserOnboarded
                    ? <Navigate to="/dashboard" replace />
                    : <Onboarding user={user} onProfile={updateProfile} />)
              }
            />
            <Route
              path="/dashboard"
              element={
                checkingProfile
                  ? <Loading message="Loading your dashboard..." />
                  : (profile && profile.hasUserOnboarded
                    ? <Dashboard 
                    isChatbotOpen={isChatbotOpen} 
                    setIsChatbotOpen={setIsChatbotOpen}
                    user={user}
                    isMobile={isMobile()}
                    />
                    : <Navigate to="/onboarding" replace />)
              }
            />
            <Route
              path="/dashboard/:ticker"
              element={
                checkingProfile
                  ? <Loading message="Loading ticker..." />
                  : (profile && profile.hasUserOnboarded
                    ? <Ticker user={user} isMobile={isMobile()} />
                    : <Navigate to="/onboarding" replace />)
              }
            />
            <Route
              path="/portfolio"
              element={(profile && profile.hasUserOnboarded)
                ? <Portfolio isChatbotOpen={isChatbotOpen} setIsChatbotOpen={setIsChatbotOpen} user={user} />
                : <Navigate to="/onboarding" replace />}
            />
          </Routes>
        </div>
        {!isOnboarding && (
          <Chatbot isOpen={isChatbotOpen} setIsOpen={setIsChatbotOpen} user={user}/>
        )}
      </div>
    </div>
  );
}

function App() {
  const [user, setUser] = useState(null);
  const [profile, setProfile] = useState(() => {
    // Load cached profile immediately to avoid loading screen for returning users
    try {
      const stored = localStorage.getItem('br_profile');
      if (stored) {
        const { data, expiry } = JSON.parse(stored);
        if (expiry > Date.now()) return data;
        localStorage.removeItem('br_profile');
      }
    } catch { }
    return null;
  });
  const [checkingProfile, setCheckingProfile] = useState(false);
  const profileRequestedRef = useRef(false);

// Theme state - no localStorage, defaults to light on each session
const [theme, setTheme] = useState('light');
useEffect(() => {
  const root = document.documentElement;
  if (theme === 'dark') {
    root.classList.add('theme-dark');
  } else {
    root.classList.remove('theme-dark');
  }
  // Removed localStorage.setItem - no persistence
}, [theme]);

  useEffect(() => {
    const stored = localStorage.getItem('br_user');
    if (stored) {
      const { data, expiry } = JSON.parse(stored);
      if (expiry > Date.now()) setUser(data);
      else localStorage.removeItem('br_user');
    }
  }, []);

  const handleLoginSuccess = (userData) => {
    const item = { data: userData, expiry: Date.now() + (60 * 60 * 1000) };
    localStorage.setItem('br_user', JSON.stringify(item));
    setUser(userData);
    // Clear profile on new login to force fresh fetch
    setProfile(null);
    localStorage.removeItem('br_profile');
    profileRequestedRef.current = false;
  };

  const handleLogout = () => {
    setUser(null);
    localStorage.removeItem('br_user');
    localStorage.removeItem('br_profile');
    setProfile(null);
    profileRequestedRef.current = false;
    // Update URL immediately
    try { window.history.replaceState({}, '', '/'); } catch { }
  };

  const updateProfile = (profileData) => {
    setProfile(profileData);
    // Update cache
    const item = { data: profileData, expiry: Date.now() + (60 * 60 * 1000) };
    try {
      localStorage.setItem('br_profile', JSON.stringify(item));
    } catch { }
  };

  useEffect(() => {
    let cancelled = false;
    async function fetchProfile() {
      if (!user) return;
      if (profileRequestedRef.current) return; // guard duplicate fetches (StrictMode)
      profileRequestedRef.current = true;

      // Check if we have a fresh cached profile
      let hasCachedProfile = false;
      try {
        const stored = localStorage.getItem('br_profile');
        if (stored) {
          const { expiry } = JSON.parse(stored);
          hasCachedProfile = expiry > Date.now();
        }
      } catch { }

      // Only show loading spinner for new users without cached profile
      if (!hasCachedProfile) {
        setCheckingProfile(true);
      }

      try {
        const res = await fetch(`${VITE_APP_API_URL}/api/user`, {
          method: 'GET',
          headers: { 'Authorization': `Bearer ${user.token}` }
        });
        const data = await res.json();
        if (!cancelled && res.ok) {
          updateProfile(data);
        }
      } finally {
        if (!cancelled) setCheckingProfile(false);
      }
    }
    fetchProfile();
    return () => { cancelled = true; };
  }, [user]);

  if (!user) {
    return (
      <GoogleOAuthProvider clientId={VITE_APP_GOOGLE_CLIENT_ID}>
        <Router>
          <Routes>
            <Route path="*" element={<Login onLoginSuccess={handleLoginSuccess} />} />
          </Routes>
        </Router>
      </GoogleOAuthProvider>
    );
  }

  return (
    <GoogleOAuthProvider clientId={VITE_APP_GOOGLE_CLIENT_ID}>
      <Router>
        <AppContent
          user={user}
          profile={profile}
          checkingProfile={checkingProfile}
          updateProfile={updateProfile}
          handleLogout={handleLogout}
          theme={theme}
          setTheme={setTheme}
        />
      </Router>
    </GoogleOAuthProvider>
  );
}

export default App;