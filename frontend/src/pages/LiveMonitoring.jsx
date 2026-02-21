import React, { useState, useEffect, useMemo } from 'react';
import { useParams } from 'react-router-dom';
import axios from 'axios';
import { Radio, AlertCircle, RefreshCw } from 'lucide-react';

const API_BASE = (import.meta.env.VITE_API_BASE || '').replace(/\/$/, '').replace(/\/api$/, '');
const buildDefaultMjpegBases = () => {
  if (typeof window === 'undefined') return [''];
  const { protocol, hostname } = window.location;
  const directHostBase = `${protocol}//${hostname}:8090`;

    // Priority: explicit env -> same-origin proxy -> direct stream-manager port fallback
  const candidates = [
    import.meta.env.VITE_MJPEG_BASE,
    import.meta.env.VITE_STREAM_BASE,
    '',
    directHostBase,
  ];

  return candidates
    .filter(Boolean)
    .map((base) => String(base).replace(/\/$/, ''))
    .filter((base, idx, arr) => arr.indexOf(base) === idx);
};

const LiveMonitoring = () => {
  const { cameraId: urlCameraId } = useParams();
  const [cameras, setCameras] = useState([]);
  const [selectedCamera, setSelectedCamera] = useState(urlCameraId || null);
  const [activeTracks, setActiveTracks] = useState([]);
  const activeWindowSeconds = Number(import.meta.env.VITE_TRACK_ACTIVE_WINDOW_SECONDS || 8);
  const [stats, setStats] = useState(null);
  const [loading, setLoading] = useState(true);
  const mjpegBases = useMemo(() => buildDefaultMjpegBases(), []);
  const [streamBaseIndex, setStreamBaseIndex] = useState(0);
  const [streamKey, setStreamKey] = useState(Date.now());
  
  useEffect(() => {
    fetchCameras();
  }, []);
  
  useEffect(() => {
    if (!selectedCamera) return;
    
    const fetchData = async () => {
      try {
        const [tracksRes, statsRes] = await Promise.all([
          axios.get(`${API_BASE}/api/tracks/${selectedCamera}`),
          axios.get(`${API_BASE}/api/cameras/${selectedCamera}/stats`)
        ]);
        
        setActiveTracks(tracksRes.data);
        setStats(statsRes.data);
      } catch (err) {
        console.error('Error fetching data:', err);
      }
    };
    
    fetchData();
    const interval = setInterval(fetchData, 2000); // Update every 2s
    
    return () => clearInterval(interval);
  }, [selectedCamera]);
  
  const fetchCameras = async () => {
    try {
      const response = await axios.get(`${API_BASE}/api/cameras`);
      setCameras(response.data);
      
      if (!selectedCamera && response.data.length > 0) {
        setSelectedCamera(response.data[0].camera_id);
      }
      
      setLoading(false);
    } catch (err) {
      console.error('Error fetching cameras:', err);
      setLoading(false);
    }
  };
  
  const refreshStream = () => {
    setStreamBaseIndex(0);
    setStreamKey(Date.now());
  };
  
  useEffect(() => {
    setStreamBaseIndex(0);
    setStreamKey(Date.now());
  }, [selectedCamera]);

  if (loading) {
    return (
      <div className="flex items-center justify-center h-64">
        <div className="animate-spin rounded-full h-12 w-12 border-b-2 border-blue-600"></div>
      </div>
    );
  }
  
  if (cameras.length === 0) {
    return (
      <div className="bg-yellow-50 border border-yellow-200 rounded-lg p-6">
        <AlertCircle className="text-yellow-600 mb-2" size={24} />
        <p className="text-yellow-800 font-semibold">No cameras configured</p>
        <p className="text-yellow-700 mt-1">Go to Camera Management to add cameras.</p>
      </div>
    );
  }
  
  const camera = cameras.find(c => c.camera_id === selectedCamera);
  const streamBase = mjpegBases[streamBaseIndex] || '';
  
  return (
    <div>
      <div className="mb-6 flex items-center justify-between">
        <div>
          <h1 className="text-3xl font-bold text-gray-900">Live Monitoring</h1>
          <p className="text-gray-600 mt-1">Real-time vehicle tracking and LPR</p>
        </div>
        
        {/* Camera selector */}
        <select
          value={selectedCamera || ''}
          onChange={(e) => setSelectedCamera(e.target.value)}
          className="px-4 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500"
        >
          {cameras.map(cam => (
            <option key={cam.camera_id} value={cam.camera_id}>
              {cam.name || cam.camera_id}
            </option>
          ))}
        </select>
      </div>
      
      {camera && (
        <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
          {/* Video Stream */}
          <div className="lg:col-span-2">
            <div className="bg-white rounded-lg shadow p-4">
              <div className="flex items-center justify-between mb-3">
                <div className="flex items-center gap-2">
                  <Radio className="text-red-500" size={20} />
                  <h2 className="text-lg font-semibold">Live Stream</h2>
                  <span className="px-2 py-1 bg-red-100 text-red-700 text-xs rounded-full">
                    LIVE
                  </span>
                </div>
                
                <button
                  onClick={refreshStream}
                  className="px-3 py-1 bg-gray-100 hover:bg-gray-200 rounded-lg flex items-center gap-2 text-sm"
                >
                  <RefreshCw size={16} />
                  Refresh
                </button>
              </div>
              
              <div className="bg-black rounded-lg overflow-hidden aspect-video">
                <img
                  key={streamKey}
                  src={`${streamBase}/stream/${selectedCamera}?t=${streamKey}`}
                  alt="Live stream"
                  className="w-full h-full object-contain"
                  onError={(e) => {
                    if (streamBaseIndex < mjpegBases.length - 1) {
                      setStreamBaseIndex((idx) => idx + 1);
                      setStreamKey(Date.now());
                      return;
                    }
                    e.target.src = 'data:image/svg+xml,%3Csvg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 800 450"%3E%3Crect fill="%23333" width="800" height="450"/%3E%3Ctext x="400" y="225" text-anchor="middle" fill="%23666" font-size="20" font-family="sans-serif"%3EStream Unavailable%3C/text%3E%3C/svg%3E';
                  }}
                />
              </div>
              
              {/* Camera Stats */}
              {stats && (
                <div className="grid grid-cols-3 gap-4 mt-4">
                  <div className="text-center p-3 bg-gray-50 rounded-lg">
                    <p className="text-sm text-gray-600">FPS</p>
                    <p className="text-2xl font-bold">{stats.fps_actual?.toFixed(1) || '0.0'}</p>
                  </div>
                  <div className="text-center p-3 bg-gray-50 rounded-lg">
                    <p className="text-sm text-gray-600">Vehicles</p>
                    <p className="text-2xl font-bold">{stats.vehicle_count || 0}</p>
                  </div>
                  <div className="text-center p-3 bg-gray-50 rounded-lg">
                    <p className="text-sm text-gray-600">Success Rate</p>
                    <p className="text-2xl font-bold">
                      {stats.success_rate?.toFixed(0) || 0}%
                    </p>
                  </div>
                </div>
              )}
            </div>
          </div>
          
          {/* Active Tracks */}
          <div className="lg:col-span-1">
            <div className="bg-white rounded-lg shadow p-4">
              <h2 className="text-lg font-semibold mb-1">
                Active Tracks ({activeTracks.length})
              </h2>
              <p className="text-xs text-gray-500 mb-4">
                Showing vehicles seen in the last {activeWindowSeconds}s
              </p>
              
              <div className="space-y-3 max-h-[600px] overflow-y-auto">
                {activeTracks.length === 0 ? (
                  <p className="text-gray-500 text-center py-8">No active tracks</p>
                ) : (
                  activeTracks.map(track => (
                    <div
                      key={track.track_id}
                      className={`p-3 rounded-lg border-2 ${
                        track.entered_zone 
                          ? 'border-green-500 bg-green-50' 
                          : 'border-gray-200 bg-gray-50'
                      }`}
                    >
                      <div className="flex items-center justify-between mb-2">
                        <span className="font-semibold text-sm">
                          Track #{track.track_id}
                        </span>
                        <span className={`px-2 py-1 text-xs rounded-full ${
                          track.entered_zone
                            ? 'bg-green-200 text-green-800'
                            : 'bg-gray-200 text-gray-700'
                        }`}>
                          {track.entered_zone ? 'IN ZONE' : 'OUTSIDE'}
                        </span>
                      </div>
                      
                      <div className="text-xs space-y-1 text-gray-600">
                        <div className="flex justify-between">
                          <span>Type:</span>
                          <span className="font-medium text-gray-900">
                            {track.vehicle_type || 'Unknown'}
                          </span>
                        </div>
                        
                        {track.lpr_triggered && track.plate_text && (
                          <div className="mt-2 p-2 bg-white rounded border border-green-300">
                            <p className="text-xs text-gray-600 mb-1">License Plate:</p>
                            <p className="font-bold text-green-700">
                              {track.plate_text}
                            </p>
                            <p className="text-xs text-gray-500">
                              Confidence: {(track.plate_confidence * 100).toFixed(1)}%
                            </p>
                          </div>
                        )}

                        {track.lpr_triggered && !track.plate_text && (
                          <div className="mt-2 p-2 bg-white rounded border border-amber-300 text-amber-700 text-xs">
                            LPR triggered, waiting for plate result
                          </div>
                        )}

                        <div className="flex justify-between">
                          <span>Last seen:</span>
                          <span className="font-medium">{track.seconds_since_seen ?? 0}s ago</span>
                        </div>
                        
                        <div className="flex justify-between pt-2 border-t border-gray-200 mt-2">
                          <span>Duration:</span>
                          <span className="font-medium">
                            {track.duration_seconds || 0}s
                          </span>
                        </div>
                      </div>
                    </div>
                  ))
                )}
              </div>
            </div>
          </div>
        </div>
      )}
    </div>
  );
};

export default LiveMonitoring;
