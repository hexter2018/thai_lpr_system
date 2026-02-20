import React, { useState, useEffect } from 'react';
import axios from 'axios';
import { Plus, Edit, Trash2, Save, X, MapPin } from 'lucide-react';

const API_BASE = (import.meta.env.VITE_API_BASE || '').replace(/\/$/, '');

const CameraManagement = () => {
  const [cameras, setCameras] = useState([]);
  const [loading, setLoading] = useState(true);
  const [editing, setEditing] = useState(null);
  const [formData, setFormData] = useState({
    camera_id: '',
    name: '',
    rtsp_url: '',
    zone_enabled: true,
    zone_polygon: [],
    fps_target: 10.0,
    codec: 'h264'
  });
  
  useEffect(() => {
    fetchCameras();
  }, []);
  
  const fetchCameras = async () => {
    try {
      const response = await axios.get(`${API_BASE}/api/cameras`);
      setCameras(response.data);
      setLoading(false);
    } catch (err) {
      console.error('Error fetching cameras:', err);
      setLoading(false);
    }
  };
  
  const handleSubmit = async (e) => {
    e.preventDefault();
    
    try {
      await axios.post(`${API_BASE}/api/cameras`, formData);
      
      alert('Camera saved successfully!');
      fetchCameras();
      resetForm();
    } catch (err) {
      console.error('Error saving camera:', err);
      alert('Error saving camera. Please check the console.');
    }
  };
  
  const handleEdit = (camera) => {
    setEditing(camera.camera_id);
    setFormData({
      camera_id: camera.camera_id,
      name: camera.name,
      rtsp_url: camera.rtsp_url,
      zone_enabled: camera.zone_enabled,
      zone_polygon: camera.zone_polygon || [],
      fps_target: camera.fps_target,
      codec: camera.codec || 'h264'
    });
  };
  
  const handleDelete = async (cameraId) => {
    if (!confirm('Are you sure you want to delete this camera?')) return;
    
    try {
      await axios.delete(`${API_BASE}/api/cameras/${cameraId}`);
      alert('Camera deleted successfully!');
      fetchCameras();
    } catch (err) {
      console.error('Error deleting camera:', err);
      alert('Error deleting camera.');
    }
  };
  
  const resetForm = () => {
    setEditing(null);
    setFormData({
      camera_id: '',
      name: '',
      rtsp_url: '',
      zone_enabled: true,
      zone_polygon: [],
      fps_target: 10.0,
      codec: 'h264'
    });
  };
  
  const addZonePoint = () => {
    setFormData(prev => ({
      ...prev,
      zone_polygon: [...prev.zone_polygon, { x: 0, y: 0 }]
    }));
  };
  
  const updateZonePoint = (index, axis, value) => {
    const newPolygon = [...formData.zone_polygon];
    newPolygon[index][axis] = parseInt(value) || 0;
    setFormData(prev => ({ ...prev, zone_polygon: newPolygon }));
  };
  
  const removeZonePoint = (index) => {
    setFormData(prev => ({
      ...prev,
      zone_polygon: prev.zone_polygon.filter((_, i) => i !== index)
    }));
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
      <div className="mb-6 flex items-center justify-between">
        <div>
          <h1 className="text-3xl font-bold text-gray-900">Camera Management</h1>
          <p className="text-gray-600 mt-1">Configure cameras and detection zones</p>
        </div>
        
        {!editing && (
          <button
            onClick={() => setEditing('new')}
            className="px-4 py-2 bg-blue-600 hover:bg-blue-700 text-white rounded-lg flex items-center gap-2"
          >
            <Plus size={20} />
            Add Camera
          </button>
        )}
      </div>
      
      {/* Camera Form */}
      {editing && (
        <div className="bg-white rounded-lg shadow p-6 mb-6">
          <div className="flex items-center justify-between mb-4">
            <h2 className="text-xl font-semibold">
              {editing === 'new' ? 'Add New Camera' : `Edit ${formData.name}`}
            </h2>
            <button
              onClick={resetForm}
              className="text-gray-500 hover:text-gray-700"
            >
              <X size={24} />
            </button>
          </div>
          
          <form onSubmit={handleSubmit} className="space-y-4">
            <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
              <div>
                <label className="block text-sm font-medium text-gray-700 mb-1">
                  Camera ID *
                </label>
                <input
                  type="text"
                  required
                  disabled={editing !== 'new'}
                  value={formData.camera_id}
                  onChange={(e) => setFormData(prev => ({ ...prev, camera_id: e.target.value }))}
                  className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500 disabled:bg-gray-100"
                  placeholder="gate1"
                />
              </div>
              
              <div>
                <label className="block text-sm font-medium text-gray-700 mb-1">
                  Display Name *
                </label>
                <input
                  type="text"
                  required
                  value={formData.name}
                  onChange={(e) => setFormData(prev => ({ ...prev, name: e.target.value }))}
                  className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500"
                  placeholder="Main Gate"
                />
              </div>
            </div>
            
            <div>
              <label className="block text-sm font-medium text-gray-700 mb-1">
                RTSP URL *
              </label>
              <input
                type="text"
                required
                value={formData.rtsp_url}
                onChange={(e) => setFormData(prev => ({ ...prev, rtsp_url: e.target.value }))}
                className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500 font-mono text-sm"
                placeholder="rtsp://username:password@192.168.1.100/stream"
              />
            </div>
            
            <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
              <div>
                <label className="block text-sm font-medium text-gray-700 mb-1">
                  Target FPS
                </label>
                <input
                  type="number"
                  step="0.1"
                  value={formData.fps_target}
                  onChange={(e) => setFormData(prev => ({ ...prev, fps_target: parseFloat(e.target.value) }))}
                  className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500"
                />
              </div>
              
              <div>
                <label className="block text-sm font-medium text-gray-700 mb-1">
                  Codec
                </label>
                <select
                  value={formData.codec}
                  onChange={(e) => setFormData(prev => ({ ...prev, codec: e.target.value }))}
                  className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500"
                >
                  <option value="h264">H.264</option>
                  <option value="h265">H.265 (HEVC)</option>
                </select>
              </div>
            </div>
            
            <div className="flex items-center gap-2">
              <input
                type="checkbox"
                id="zone_enabled"
                checked={formData.zone_enabled}
                onChange={(e) => setFormData(prev => ({ ...prev, zone_enabled: e.target.checked }))}
                className="w-4 h-4 text-blue-600 rounded focus:ring-blue-500"
              />
              <label htmlFor="zone_enabled" className="text-sm font-medium text-gray-700">
                Enable Detection Zone
              </label>
            </div>
            
            {/* Zone Polygon */}
            {formData.zone_enabled && (
              <div className="border border-gray-300 rounded-lg p-4">
                <div className="flex items-center justify-between mb-3">
                  <label className="text-sm font-medium text-gray-700 flex items-center gap-2">
                    <MapPin size={16} />
                    Detection Zone Polygon
                  </label>
                  <button
                    type="button"
                    onClick={addZonePoint}
                    className="px-3 py-1 bg-green-500 hover:bg-green-600 text-white text-sm rounded"
                  >
                    Add Point
                  </button>
                </div>
                
                <div className="space-y-2 max-h-48 overflow-y-auto">
                  {formData.zone_polygon.map((point, index) => (
                    <div key={index} className="flex items-center gap-2">
                      <span className="text-sm text-gray-600 w-16">Point {index + 1}:</span>
                      <input
                        type="number"
                        value={point.x}
                        onChange={(e) => updateZonePoint(index, 'x', e.target.value)}
                        placeholder="X"
                        className="w-24 px-2 py-1 border border-gray-300 rounded text-sm"
                      />
                      <input
                        type="number"
                        value={point.y}
                        onChange={(e) => updateZonePoint(index, 'y', e.target.value)}
                        placeholder="Y"
                        className="w-24 px-2 py-1 border border-gray-300 rounded text-sm"
                      />
                      <button
                        type="button"
                        onClick={() => removeZonePoint(index)}
                        className="text-red-500 hover:text-red-700"
                      >
                        <Trash2 size={16} />
                      </button>
                    </div>
                  ))}
                  
                  {formData.zone_polygon.length === 0 && (
                    <p className="text-sm text-gray-500 text-center py-4">
                      No zone points defined. Click "Add Point" to start.
                    </p>
                  )}
                </div>
                
                <p className="text-xs text-gray-500 mt-2">
                  Define polygon points in image coordinates (e.g., 0,0 is top-left)
                </p>
              </div>
            )}
            
            <div className="flex gap-3">
              <button
                type="submit"
                className="px-6 py-2 bg-blue-600 hover:bg-blue-700 text-white rounded-lg flex items-center gap-2"
              >
                <Save size={20} />
                Save Camera
              </button>
              <button
                type="button"
                onClick={resetForm}
                className="px-6 py-2 bg-gray-200 hover:bg-gray-300 text-gray-700 rounded-lg"
              >
                Cancel
              </button>
            </div>
          </form>
        </div>
      )}
      
      {/* Camera List */}
      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
        {cameras.map(camera => (
          <div key={camera.camera_id} className="bg-white rounded-lg shadow p-4">
            <div className="flex items-start justify-between mb-3">
              <div>
                <h3 className="font-semibold text-lg">{camera.name}</h3>
                <p className="text-sm text-gray-600">{camera.camera_id}</p>
              </div>
              <span className={`px-2 py-1 text-xs rounded-full ${
                camera.status === 'active' 
                  ? 'bg-green-100 text-green-800'
                  : 'bg-gray-100 text-gray-800'
              }`}>
                {camera.status || 'inactive'}
              </span>
            </div>
            
            <div className="text-sm space-y-1 text-gray-600 mb-4">
              <div className="flex justify-between">
                <span>FPS Target:</span>
                <span className="font-medium">{camera.fps_target}</span>
              </div>
              <div className="flex justify-between">
                <span>Codec:</span>
                <span className="font-medium">{camera.codec?.toUpperCase()}</span>
              </div>
              <div className="flex justify-between">
                <span>Zone:</span>
                <span className={`font-medium ${camera.zone_enabled ? 'text-green-600' : 'text-gray-400'}`}>
                  {camera.zone_enabled ? 'Enabled' : 'Disabled'}
                </span>
              </div>
            </div>
            
            <div className="flex gap-2">
              <button
                onClick={() => handleEdit(camera)}
                className="flex-1 px-3 py-2 bg-blue-50 hover:bg-blue-100 text-blue-700 rounded text-sm flex items-center justify-center gap-1"
              >
                <Edit size={16} />
                Edit
              </button>
              <button
                onClick={() => handleDelete(camera.camera_id)}
                className="flex-1 px-3 py-2 bg-red-50 hover:bg-red-100 text-red-700 rounded text-sm flex items-center justify-center gap-1"
              >
                <Trash2 size={16} />
                Delete
              </button>
            </div>
          </div>
        ))}
      </div>
      
      {cameras.length === 0 && !editing && (
        <div className="bg-gray-50 rounded-lg p-12 text-center">
          <p className="text-gray-600 mb-4">No cameras configured yet</p>
          <button
            onClick={() => setEditing('new')}
            className="px-4 py-2 bg-blue-600 hover:bg-blue-700 text-white rounded-lg inline-flex items-center gap-2"
          >
            <Plus size={20} />
            Add Your First Camera
          </button>
        </div>
      )}
    </div>
  );
};

export default CameraManagement;
