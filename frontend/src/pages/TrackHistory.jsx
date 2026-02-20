import React, { useState, useEffect } from 'react';
import axios from 'axios';
import { History, Search, Filter } from 'lucide-react';

const API_BASE = import.meta.env.VITE_API_BASE || 'http://localhost:8000';

const TrackHistory = () => {
  const [tracks, setTracks] = useState([]);
  const [loading, setLoading] = useState(true);
  const [cameras, setCameras] = useState([]);
  const [selectedCamera, setSelectedCamera] = useState('all');
  const [searchPlate, setSearchPlate] = useState('');
  const [dateFilter, setDateFilter] = useState('today');
  
  useEffect(() => {
    fetchCameras();
  }, []);
  
  useEffect(() => {
    fetchTracks();
  }, [selectedCamera, dateFilter]);
  
  const fetchCameras = async () => {
    try {
      const response = await axios.get(`${API_BASE}/api/cameras`);
      setCameras(response.data);
    } catch (err) {
      console.error('Error fetching cameras:', err);
    }
  };
  
  const fetchTracks = async () => {
    try {
      const params = {
        camera_id: selectedCamera !== 'all' ? selectedCamera : undefined,
        date_range: dateFilter,
        plate_text: searchPlate || undefined
      };
      
      const response = await axios.get(`${API_BASE}/api/tracks/history`, { params });
      setTracks(response.data);
      setLoading(false);
    } catch (err) {
      console.error('Error fetching tracks:', err);
      setLoading(false);
    }
  };
  
  const handleSearch = (e) => {
    e.preventDefault();
    fetchTracks();
  };
  
  if (loading) {
    return (
      <div className="flex items-center justify-center h-64">
        <div className="animate-spin rounded-full h-12 w-12 border-b-2 border-blue-600"></div>
      </div>
    );
  }
  
  return (
    <div>
      <div className="mb-6">
        <h1 className="text-3xl font-bold text-gray-900">Track History</h1>
        <p className="text-gray-600 mt-1">Historical vehicle tracking records</p>
      </div>
      
      {/* Filters */}
      <div className="bg-white rounded-lg shadow p-4 mb-6">
        <div className="grid grid-cols-1 md:grid-cols-4 gap-4">
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1">
              Camera
            </label>
            <select
              value={selectedCamera}
              onChange={(e) => setSelectedCamera(e.target.value)}
              className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500"
            >
              <option value="all">All Cameras</option>
              {cameras.map(cam => (
                <option key={cam.camera_id} value={cam.camera_id}>
                  {cam.name}
                </option>
              ))}
            </select>
          </div>
          
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1">
              Date Range
            </label>
            <select
              value={dateFilter}
              onChange={(e) => setDateFilter(e.target.value)}
              className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500"
            >
              <option value="today">Today</option>
              <option value="yesterday">Yesterday</option>
              <option value="week">Last 7 Days</option>
              <option value="month">Last 30 Days</option>
            </select>
          </div>
          
          <div className="md:col-span-2">
            <label className="block text-sm font-medium text-gray-700 mb-1">
              Search Plate
            </label>
            <form onSubmit={handleSearch} className="flex gap-2">
              <input
                type="text"
                value={searchPlate}
                onChange={(e) => setSearchPlate(e.target.value)}
                placeholder="Enter plate number..."
                className="flex-1 px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500"
              />
              <button
                type="submit"
                className="px-4 py-2 bg-blue-600 hover:bg-blue-700 text-white rounded-lg flex items-center gap-2"
              >
                <Search size={18} />
                Search
              </button>
            </form>
          </div>
        </div>
      </div>
      
      {/* Tracks Table */}
      <div className="bg-white rounded-lg shadow overflow-hidden">
        <table className="w-full">
          <thead className="bg-gray-50 border-b border-gray-200">
            <tr>
              <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">
                Track ID
              </th>
              <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">
                Camera
              </th>
              <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">
                Vehicle Type
              </th>
              <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">
                License Plate
              </th>
              <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">
                Province
              </th>
              <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">
                Confidence
              </th>
              <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">
                Time
              </th>
              <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">
                Status
              </th>
            </tr>
          </thead>
          <tbody className="divide-y divide-gray-200">
            {tracks.length === 0 ? (
              <tr>
                <td colSpan="8" className="px-4 py-8 text-center text-gray-500">
                  No tracks found for selected filters
                </td>
              </tr>
            ) : (
              tracks.map(track => (
                <tr key={track.track_id} className="hover:bg-gray-50">
                  <td className="px-4 py-3 text-sm font-mono">
                    #{track.track_id}
                  </td>
                  <td className="px-4 py-3 text-sm">
                    {track.camera_name}
                  </td>
                  <td className="px-4 py-3 text-sm">
                    {track.vehicle_type || 'Unknown'}
                  </td>
                  <td className="px-4 py-3 text-sm font-semibold">
                    {track.plate_text || '-'}
                  </td>
                  <td className="px-4 py-3 text-sm">
                    {track.province || '-'}
                  </td>
                  <td className="px-4 py-3 text-sm">
                    {track.plate_confidence ? (
                      <span className={`px-2 py-1 rounded-full text-xs ${
                        track.plate_confidence >= 0.8
                          ? 'bg-green-100 text-green-800'
                          : track.plate_confidence >= 0.6
                          ? 'bg-yellow-100 text-yellow-800'
                          : 'bg-red-100 text-red-800'
                      }`}>
                        {(track.plate_confidence * 100).toFixed(0)}%
                      </span>
                    ) : '-'}
                  </td>
                  <td className="px-4 py-3 text-sm text-gray-600">
                    {new Date(track.first_seen).toLocaleString()}
                  </td>
                  <td className="px-4 py-3 text-sm">
                    <span className={`px-2 py-1 rounded-full text-xs ${
                      track.verification_status === 'VERIFIED'
                        ? 'bg-green-100 text-green-800'
                        : track.verification_status === 'PENDING'
                        ? 'bg-yellow-100 text-yellow-800'
                        : 'bg-gray-100 text-gray-800'
                    }`}>
                      {track.verification_status || 'N/A'}
                    </span>
                  </td>
                </tr>
              ))
            )}
          </tbody>
        </table>
      </div>
      
      {/* Summary Stats */}
      <div className="grid grid-cols-1 md:grid-cols-3 gap-4 mt-6">
        <div className="bg-white rounded-lg shadow p-4">
          <p className="text-sm text-gray-600">Total Tracks</p>
          <p className="text-2xl font-bold mt-1">{tracks.length}</p>
        </div>
        <div className="bg-white rounded-lg shadow p-4">
          <p className="text-sm text-gray-600">With LPR</p>
          <p className="text-2xl font-bold mt-1">
            {tracks.filter(t => t.plate_text).length}
          </p>
        </div>
        <div className="bg-white rounded-lg shadow p-4">
          <p className="text-sm text-gray-600">Verified</p>
          <p className="text-2xl font-bold mt-1">
            {tracks.filter(t => t.verification_status === 'VERIFIED').length}
          </p>
        </div>
      </div>
    </div>
  );
};

export default TrackHistory;
