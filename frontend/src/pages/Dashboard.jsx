import React, { useState, useEffect } from 'react';
import { TrendingUp, TrendingDown, Camera, CheckCircle, XCircle, Activity } from 'lucide-react';
import axios from 'axios';

const API_BASE = import.meta.env.VITE_API_BASE || 'http://localhost:8000';

const StatCard = ({ title, value, change, icon: Icon, trend }) => (
  <div className="bg-white rounded-lg shadow p-6">
    <div className="flex items-center justify-between">
      <div>
        <p className="text-sm text-gray-600 mb-1">{title}</p>
        <p className="text-3xl font-bold">{value}</p>
        {change !== undefined && (
          <div className={`flex items-center gap-1 mt-2 text-sm ${
            trend === 'up' ? 'text-green-600' : 'text-red-600'
          }`}>
            {trend === 'up' ? <TrendingUp size={16} /> : <TrendingDown size={16} />}
            <span>{change}%</span>
          </div>
        )}
      </div>
      <div className="p-3 bg-blue-50 rounded-full">
        <Icon className="text-blue-600" size={24} />
      </div>
    </div>
  </div>
);

const Dashboard = () => {
  const [stats, setStats] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  
  useEffect(() => {
    const fetchStats = async () => {
      try {
        const response = await axios.get(`${API_BASE}/api/analytics/dashboard`);
        setStats(response.data);
        setLoading(false);
      } catch (err) {
        setError(err.message);
        setLoading(false);
      }
    };
    
    fetchStats();
    const interval = setInterval(fetchStats, 5000); // Update every 5s
    
    return () => clearInterval(interval);
  }, []);
  
  if (loading) {
    return (
      <div className="flex items-center justify-center h-64">
        <div className="animate-spin rounded-full h-12 w-12 border-b-2 border-blue-600"></div>
      </div>
    );
  }
  
  if (error) {
    return (
      <div className="bg-red-50 border border-red-200 rounded-lg p-4">
        <p className="text-red-800">Error loading dashboard: {error}</p>
      </div>
    );
  }
  
  const {
    total_cameras = 0,
    active_cameras = 0,
    total_vehicles_today = 0,
    total_lpr_attempts_today = 0,
    total_lpr_success_today = 0,
    success_rate_today = 0,
    alpr_count_today = 0,
    mlpr_count_today = 0,
    master_plate_count = 0,
    pending_verification = 0
  } = stats || {};
  
  return (
    <div>
      <div className="mb-8">
        <h1 className="text-3xl font-bold text-gray-900">Dashboard</h1>
        <p className="text-gray-600 mt-1">Real-time system overview</p>
      </div>
      
      {/* Top Stats */}
      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-6 mb-8">
        <StatCard
          title="Active Cameras"
          value={`${active_cameras}/${total_cameras}`}
          icon={Camera}
        />
        <StatCard
          title="Vehicles Today"
          value={total_vehicles_today.toLocaleString()}
          icon={Activity}
        />
        <StatCard
          title="LPR Success Rate"
          value={`${success_rate_today.toFixed(1)}%`}
          change={success_rate_today >= 80 ? '+5.2' : '-2.1'}
          trend={success_rate_today >= 80 ? 'up' : 'down'}
          icon={CheckCircle}
        />
        <StatCard
          title="Pending Verification"
          value={pending_verification}
          icon={XCircle}
        />
      </div>
      
      {/* LPR Performance */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6 mb-8">
        <div className="bg-white rounded-lg shadow p-6">
          <h2 className="text-xl font-semibold mb-4">LPR Performance Today</h2>
          <div className="space-y-4">
            <div className="flex justify-between items-center">
              <span className="text-gray-600">Total Attempts</span>
              <span className="font-semibold text-lg">{total_lpr_attempts_today}</span>
            </div>
            <div className="flex justify-between items-center">
              <span className="text-gray-600">Successful</span>
              <span className="font-semibold text-lg text-green-600">{total_lpr_success_today}</span>
            </div>
            <div className="flex justify-between items-center">
              <span className="text-gray-600">Failed</span>
              <span className="font-semibold text-lg text-red-600">
                {total_lpr_attempts_today - total_lpr_success_today}
              </span>
            </div>
            
            {/* Progress bar */}
            <div className="mt-4">
              <div className="flex justify-between text-sm mb-2">
                <span>Success Rate</span>
                <span className="font-semibold">{success_rate_today.toFixed(1)}%</span>
              </div>
              <div className="w-full bg-gray-200 rounded-full h-3">
                <div
                  className="bg-green-500 h-3 rounded-full transition-all duration-500"
                  style={{ width: `${success_rate_today}%` }}
                />
              </div>
            </div>
          </div>
        </div>
        
        {/* ALPR vs MLPR */}
        <div className="bg-white rounded-lg shadow p-6">
          <h2 className="text-xl font-semibold mb-4">Verification Method</h2>
          <div className="space-y-4">
            <div className="flex justify-between items-center p-3 bg-green-50 rounded-lg">
              <div>
                <p className="font-semibold text-green-800">ALPR (Automatic)</p>
                <p className="text-sm text-gray-600">No manual correction</p>
              </div>
              <span className="text-2xl font-bold text-green-600">{alpr_count_today}</span>
            </div>
            
            <div className="flex justify-between items-center p-3 bg-blue-50 rounded-lg">
              <div>
                <p className="font-semibold text-blue-800">MLPR (Manual)</p>
                <p className="text-sm text-gray-600">Manually corrected</p>
              </div>
              <span className="text-2xl font-bold text-blue-600">{mlpr_count_today}</span>
            </div>
            
            <div className="mt-4 p-4 bg-gray-50 rounded-lg">
              <div className="flex justify-between items-center">
                <span className="text-gray-700">Master Plate Database</span>
                <span className="font-bold text-xl">{master_plate_count.toLocaleString()}</span>
              </div>
              <p className="text-sm text-gray-500 mt-1">Known plates for fuzzy matching</p>
            </div>
          </div>
        </div>
      </div>
      
      {/* Recent Activity */}
      <div className="bg-white rounded-lg shadow p-6">
        <h2 className="text-xl font-semibold mb-4">System Status</h2>
        <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
          <div className="flex items-center gap-3 p-3 bg-green-50 rounded-lg">
            <div className="w-3 h-3 bg-green-500 rounded-full animate-pulse"></div>
            <div>
              <p className="font-semibold text-green-800">Vehicle Detector</p>
              <p className="text-sm text-gray-600">TensorRT Engine Active</p>
            </div>
          </div>
          
          <div className="flex items-center gap-3 p-3 bg-green-50 rounded-lg">
            <div className="w-3 h-3 bg-green-500 rounded-full animate-pulse"></div>
            <div>
              <p className="font-semibold text-green-800">Plate Detector</p>
              <p className="text-sm text-gray-600">TensorRT Engine Active</p>
            </div>
          </div>
          
          <div className="flex items-center gap-3 p-3 bg-green-50 rounded-lg">
            <div className="w-3 h-3 bg-green-500 rounded-full animate-pulse"></div>
            <div>
              <p className="font-semibold text-green-800">ByteTrack</p>
              <p className="text-sm text-gray-600">Multi-vehicle Tracking</p>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
};

export default Dashboard;
