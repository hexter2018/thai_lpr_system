import React, { useState, useEffect } from 'react';
import axios from 'axios';
import { BarChart3, TrendingUp, Calendar } from 'lucide-react';

const API_BASE = import.meta.env.VITE_API_BASE || 'http://localhost:8000';

const Analytics = () => {
  const [analytics, setAnalytics] = useState(null);
  const [loading, setLoading] = useState(true);
  const [timeRange, setTimeRange] = useState('today'); // today, week, month
  
  useEffect(() => {
    fetchAnalytics();
    const interval = setInterval(fetchAnalytics, 30000); // Update every 30s
    return () => clearInterval(interval);
  }, [timeRange]);
  
  const fetchAnalytics = async () => {
    try {
      const response = await axios.get(`${API_BASE}/api/analytics/dashboard`, {
        params: { range: timeRange }
      });
      setAnalytics(response.data);
      setLoading(false);
    } catch (err) {
      console.error('Error fetching analytics:', err);
      setLoading(false);
    }
  };
  
  if (loading) {
    return (
      <div className="flex items-center justify-center h-64">
        <div className="animate-spin rounded-full h-12 w-12 border-b-2 border-blue-600"></div>
      </div>
    );
  }
  
  const {
    total_vehicles_today = 0,
    total_lpr_attempts_today = 0,
    total_lpr_success_today = 0,
    success_rate_today = 0,
    alpr_count_today = 0,
    mlpr_count_today = 0,
    alpr_accuracy = 0,
    master_plate_count = 0,
    master_match_rate = 0
  } = analytics || {};
  
  const alprPercentage = total_lpr_success_today > 0 
    ? (alpr_count_today / total_lpr_success_today * 100) 
    : 0;
  const mlprPercentage = total_lpr_success_today > 0 
    ? (mlpr_count_today / total_lpr_success_today * 100) 
    : 0;
  
  return (
    <div>
      <div className="mb-6 flex items-center justify-between">
        <div>
          <h1 className="text-3xl font-bold text-gray-900">Analytics</h1>
          <p className="text-gray-600 mt-1">Performance metrics and insights</p>
        </div>
        
        <div className="flex gap-2">
          {['today', 'week', 'month'].map(range => (
            <button
              key={range}
              onClick={() => setTimeRange(range)}
              className={`px-4 py-2 rounded-lg capitalize ${
                timeRange === range
                  ? 'bg-blue-600 text-white'
                  : 'bg-white text-gray-700 hover:bg-gray-100'
              }`}
            >
              {range}
            </button>
          ))}
        </div>
      </div>
      
      {/* Key Metrics */}
      <div className="grid grid-cols-1 md:grid-cols-3 gap-6 mb-8">
        <div className="bg-white rounded-lg shadow p-6">
          <div className="flex items-center justify-between mb-2">
            <h3 className="text-sm text-gray-600">Total Vehicles</h3>
            <BarChart3 className="text-blue-600" size={20} />
          </div>
          <p className="text-3xl font-bold">{total_vehicles_today.toLocaleString()}</p>
          <p className="text-sm text-green-600 mt-1 flex items-center gap-1">
            <TrendingUp size={14} />
            Processing
          </p>
        </div>
        
        <div className="bg-white rounded-lg shadow p-6">
          <div className="flex items-center justify-between mb-2">
            <h3 className="text-sm text-gray-600">LPR Success Rate</h3>
            <BarChart3 className="text-green-600" size={20} />
          </div>
          <p className="text-3xl font-bold">{success_rate_today.toFixed(1)}%</p>
          <p className="text-sm text-gray-600 mt-1">
            {total_lpr_success_today}/{total_lpr_attempts_today} successful
          </p>
        </div>
        
        <div className="bg-white rounded-lg shadow p-6">
          <div className="flex items-center justify-between mb-2">
            <h3 className="text-sm text-gray-600">ALPR Accuracy</h3>
            <BarChart3 className="text-purple-600" size={20} />
          </div>
          <p className="text-3xl font-bold">{alpr_accuracy.toFixed(1)}%</p>
          <p className="text-sm text-gray-600 mt-1">
            {alpr_count_today} auto-verified
          </p>
        </div>
      </div>
      
      {/* ALPR vs MLPR Breakdown */}
      <div className="bg-white rounded-lg shadow p-6 mb-8">
        <h2 className="text-xl font-semibold mb-4">Verification Method Distribution</h2>
        
        <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
          <div>
            <div className="flex justify-between mb-2">
              <span className="text-sm text-gray-600">ALPR (Automatic)</span>
              <span className="text-sm font-semibold">{alpr_count_today} ({alprPercentage.toFixed(1)}%)</span>
            </div>
            <div className="w-full bg-gray-200 rounded-full h-4">
              <div
                className="bg-green-500 h-4 rounded-full transition-all duration-500"
                style={{ width: `${alprPercentage}%` }}
              />
            </div>
          </div>
          
          <div>
            <div className="flex justify-between mb-2">
              <span className="text-sm text-gray-600">MLPR (Manual)</span>
              <span className="text-sm font-semibold">{mlpr_count_today} ({mlprPercentage.toFixed(1)}%)</span>
            </div>
            <div className="w-full bg-gray-200 rounded-full h-4">
              <div
                className="bg-blue-500 h-4 rounded-full transition-all duration-500"
                style={{ width: `${mlprPercentage}%` }}
              />
            </div>
          </div>
        </div>
        
        <div className="mt-6 p-4 bg-gray-50 rounded-lg">
          <h3 className="font-semibold mb-2">Interpretation:</h3>
          <ul className="text-sm text-gray-600 space-y-1">
            <li>• <strong>ALPR</strong>: OCR result accepted without manual correction</li>
            <li>• <strong>MLPR</strong>: OCR result corrected by operator for accuracy</li>
            <li>• Higher ALPR rate indicates better OCR model performance</li>
            <li>• MLPR samples are used for Active Learning to improve future accuracy</li>
          </ul>
        </div>
      </div>
      
      {/* Master Database Stats */}
      <div className="bg-white rounded-lg shadow p-6">
        <h2 className="text-xl font-semibold mb-4">Master Plate Database</h2>
        
        <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
          <div className="p-4 bg-blue-50 rounded-lg">
            <p className="text-sm text-gray-600 mb-1">Total Known Plates</p>
            <p className="text-3xl font-bold text-blue-700">
              {master_plate_count.toLocaleString()}
            </p>
            <p className="text-xs text-gray-500 mt-2">
              Plates stored for fuzzy matching and confidence boosting
            </p>
          </div>
          
          <div className="p-4 bg-green-50 rounded-lg">
            <p className="text-sm text-gray-600 mb-1">Master Match Rate</p>
            <p className="text-3xl font-bold text-green-700">
              {master_match_rate.toFixed(1)}%
            </p>
            <p className="text-xs text-gray-500 mt-2">
              Percentage of reads matched to known plates
            </p>
          </div>
        </div>
        
        <div className="mt-4 p-4 bg-gray-50 rounded-lg">
          <p className="text-sm text-gray-700">
            <strong>Note:</strong> Master plate database grows automatically from MLPR 
            corrections. Fuzzy matching (Levenshtein distance ≤ 1) helps correct minor 
            OCR errors and boosts confidence for known plates.
          </p>
        </div>
      </div>
    </div>
  );
};

export default Analytics;
