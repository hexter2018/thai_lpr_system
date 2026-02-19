import React from 'react';
import { BrowserRouter as Router, Routes, Route, Navigate } from 'react-router-dom';
import Layout from './components/Layout';
import Dashboard from './pages/Dashboard';
import CameraManagement from './pages/CameraManagement';
import LiveMonitoring from './pages/LiveMonitoring';
import Verification from './pages/Verification';
import Analytics from './pages/Analytics';
import TrackHistory from './pages/TrackHistory';

function App() {
  return (
    <Router>
      <Layout>
        <Routes>
          <Route path="/" element={<Navigate to="/dashboard" replace />} />
          <Route path="/dashboard" element={<Dashboard />} />
          <Route path="/cameras" element={<CameraManagement />} />
          <Route path="/live/:cameraId?" element={<LiveMonitoring />} />
          <Route path="/verification" element={<Verification />} />
          <Route path="/analytics" element={<Analytics />} />
          <Route path="/tracks" element={<TrackHistory />} />
        </Routes>
      </Layout>
    </Router>
  );
}

export default App;
