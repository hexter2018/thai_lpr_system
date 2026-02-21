import React, { useState, useEffect } from 'react';
import axios from 'axios';
import { CheckCircle, XCircle, AlertCircle, Search } from 'lucide-react';

const API_BASE = (import.meta.env.VITE_API_BASE || '').replace(/\/$/, '').replace(/\/api$/, '');

const THAI_PROVINCES = [
  'กรุงเทพมหานคร', 'กระบี่', 'กาญจนบุรี', 'กาฬสินธุ์', 'กำแพงเพชร',
  'ขอนแก่น', 'จันทบุรี', 'ฉะเชิงเทรา', 'ชลบุรี', 'ชัยนาท',
  'ชัยภูมิ', 'ชุมพร', 'เชียงราย', 'เชียงใหม่', 'ตรัง',
  'ตราด', 'ตาก', 'นครนายก', 'นครปฐม', 'นครพนม',
  'นครราชสีมา', 'นครศรีธรรมราช', 'นครสวรรค์', 'นนทบุรี', 'นราธิวาส',
  'น่าน', 'บึงกาฬ', 'บุรีรัมย์', 'ปทุมธานี', 'ประจวบคีรีขันธ์',
  'ปราจีนบุรี', 'ปัตตานี', 'พระนครศรีอยุธยา', 'พังงา', 'พัทลุง',
  'พิจิตร', 'พิษณุโลก', 'เพชรบุรี', 'เพชรบูรณ์', 'แพร่',
  'พะเยา', 'ภูเก็ต', 'มหาสารคาม', 'มุกดาหาร', 'แม่ฮ่องสอน',
  'ยะลา', 'ยโสธร', 'ร้อยเอ็ด', 'ระนอง', 'ระยอง',
  'ราชบุรี', 'ลพบุรี', 'ลำปาง', 'ลำพูน', 'เลย',
  'ศรีสะเกษ', 'สกลนคร', 'สงขลา', 'สตูล', 'สมุทรปราการ',
  'สมุทรสงคราม', 'สมุทรสาคร', 'สระแก้ว', 'สระบุรี', 'สิงห์บุรี',
  'สุโขทัย', 'สุพรรณบุรี', 'สุราษฎร์ธานี', 'สุรินทร์', 'หนองคาย',
  'หนองบัวลำภู', 'อ่างทอง', 'อำนาจเจริญ', 'อุดรธานี', 'อุตรดิตถ์',
  'อุทัยธานี', 'อุบลราชธานี'
];

const Verification = () => {
  const [pendingReads, setPendingReads] = useState([]);
  const [loading, setLoading] = useState(true);
  const [selectedRead, setSelectedRead] = useState(null);
  const [correctedText, setCorrectedText] = useState('');
  const [correctedProvince, setCorrectedProvince] = useState('');
  const [searchProvince, setSearchProvince] = useState('');
  const [submitting, setSubmitting] = useState(false);
  
  useEffect(() => {
    fetchPendingReads();
    const interval = setInterval(fetchPendingReads, 10000); // Update every 10s
    return () => clearInterval(interval);
  }, []);
  
  const fetchPendingReads = async () => {
    try {
      const response = await axios.get(`${API_BASE}/api/reads/pending`);
      setPendingReads(response.data);
      setLoading(false);
    } catch (err) {
      console.error('Error fetching pending reads:', err);
      setLoading(false);
    }
  };
  
  const handleSelectRead = (read) => {
    setSelectedRead(read);
    setCorrectedText(read.plate_text || '');
    setCorrectedProvince(read.province || '');
    setSearchProvince('');
  };
  
  const handleVerify = async (isCorrect) => {
    if (!selectedRead) return;
    
    setSubmitting(true);
    
    try {
      const payload = {
        is_correct: isCorrect,
        corrected_text: isCorrect ? null : correctedText,
        corrected_province: isCorrect ? null : correctedProvince
      };
      
      await axios.post(
        `${API_BASE}/api/reads/${selectedRead.id}/verify`,
        payload
      );
      
      // Remove from pending list
      setPendingReads(prev => prev.filter(r => r.id !== selectedRead.id));
      
      // Clear selection
      setSelectedRead(null);
      setCorrectedText('');
      setCorrectedProvince('');
      
      // Show success message
      alert(isCorrect ? 'Verified as correct (ALPR)' : 'Corrected and saved (MLPR)');
      
    } catch (err) {
      console.error('Error verifying read:', err);
      alert('Error verifying plate. Please try again.');
    } finally {
      setSubmitting(false);
    }
  };
  
  const filteredProvinces = THAI_PROVINCES.filter(p =>
    p.toLowerCase().includes(searchProvince.toLowerCase())
  );
  
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
        <h1 className="text-3xl font-bold text-gray-900">License Plate Verification</h1>
        <p className="text-gray-600 mt-1">Review and correct OCR results</p>
      </div>
      
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        {/* Pending List */}
        <div>
          <div className="bg-white rounded-lg shadow">
            <div className="p-4 border-b border-gray-200">
              <h2 className="text-lg font-semibold">
                Pending Verification ({pendingReads.length})
              </h2>
            </div>
            
            <div className="max-h-[700px] overflow-y-auto">
              {pendingReads.length === 0 ? (
                <div className="p-8 text-center text-gray-500">
                  <CheckCircle className="mx-auto mb-2" size={48} />
                  <p>All caught up! No pending verifications.</p>
                </div>
              ) : (
                <div className="divide-y divide-gray-200">
                  {pendingReads.map(read => (
                    <div
                      key={read.id}
                      onClick={() => handleSelectRead(read)}
                      className={`p-4 cursor-pointer hover:bg-gray-50 transition ${
                        selectedRead?.id === read.id ? 'bg-blue-50 border-l-4 border-blue-500' : ''
                      }`}
                    >
                      <div className="flex items-center justify-between mb-2">
                        <span className="font-mono text-lg font-bold">
                          {read.plate_text || 'NO TEXT'}
                        </span>
                        <span className={`px-2 py-1 text-xs rounded-full ${
                          read.confidence >= 0.8 
                            ? 'bg-green-100 text-green-800'
                            : read.confidence >= 0.6
                            ? 'bg-yellow-100 text-yellow-800'
                            : 'bg-red-100 text-red-800'
                        }`}>
                          {(read.confidence * 100).toFixed(0)}%
                        </span>
                      </div>
                      
                      <div className="text-sm space-y-1 text-gray-600">
                        <div className="flex justify-between">
                          <span>Province:</span>
                          <span className="font-medium">{read.province || 'Unknown'}</span>
                        </div>
                        <div className="flex justify-between">
                          <span>Camera:</span>
                          <span className="font-medium">{read.camera_name}</span>
                        </div>
                        <div className="flex justify-between">
                          <span>Track:</span>
                          <span className="font-medium">#{read.track_id}</span>
                        </div>
                        <div className="flex justify-between">
                          <span>Time:</span>
                          <span className="font-medium">
                            {new Date(read.captured_at).toLocaleTimeString()}
                          </span>
                        </div>
                      </div>
                    </div>
                  ))}
                </div>
              )}
            </div>
          </div>
        </div>
        
        {/* Verification Panel */}
        <div>
          {selectedRead ? (
            <div className="bg-white rounded-lg shadow p-6">
              <h2 className="text-lg font-semibold mb-4">Verify Plate</h2>
              
              {/* Plate Image */}
              {selectedRead.crop_path && (
                <div className="mb-6 bg-gray-100 rounded-lg p-4">
                  <img
                    src={`${API_BASE}/storage/${selectedRead.crop_path}`}
                    alt="Plate crop"
                    className="w-full max-w-md mx-auto rounded"
                    onError={(e) => {
                      e.target.style.display = 'none';
                    }}
                  />
                </div>
              )}
              
              {/* OCR Result */}
              <div className="mb-6 p-4 bg-gray-50 rounded-lg">
                <p className="text-sm text-gray-600 mb-2">OCR Result:</p>
                <p className="font-mono text-2xl font-bold text-center">
                  {selectedRead.plate_text || 'NO TEXT'}
                </p>
                <p className="text-center text-gray-600 mt-1">
                  {selectedRead.province || 'No province'}
                </p>
                <div className="flex justify-center mt-2">
                  <span className={`px-3 py-1 rounded-full text-sm ${
                    selectedRead.confidence >= 0.8 
                      ? 'bg-green-100 text-green-800'
                      : selectedRead.confidence >= 0.6
                      ? 'bg-yellow-100 text-yellow-800'
                      : 'bg-red-100 text-red-800'
                  }`}>
                    Confidence: {(selectedRead.confidence * 100).toFixed(1)}%
                  </span>
                </div>
              </div>
              
              {/* Quick Verify Buttons */}
              <div className="mb-6">
                <p className="text-sm font-semibold text-gray-700 mb-2">Is this correct?</p>
                <div className="grid grid-cols-2 gap-3">
                  <button
                    onClick={() => handleVerify(true)}
                    disabled={submitting}
                    className="px-4 py-3 bg-green-500 hover:bg-green-600 text-white rounded-lg font-semibold flex items-center justify-center gap-2 disabled:opacity-50"
                  >
                    <CheckCircle size={20} />
                    Correct (ALPR)
                  </button>
                  <button
                    onClick={() => {}} // Just to show the correction form
                    className="px-4 py-3 bg-red-500 hover:bg-red-600 text-white rounded-lg font-semibold flex items-center justify-center gap-2"
                  >
                    <XCircle size={20} />
                    Needs Correction
                  </button>
                </div>
              </div>
              
              {/* Correction Form */}
              <div className="border-t border-gray-200 pt-6">
                <p className="text-sm font-semibold text-gray-700 mb-3">
                  Manual Correction (MLPR):
                </p>
                
                <div className="space-y-4">
                  <div>
                    <label className="block text-sm font-medium text-gray-700 mb-1">
                      Corrected Plate Text
                    </label>
                    <input
                      type="text"
                      value={correctedText}
                      onChange={(e) => setCorrectedText(e.target.value)}
                      placeholder="Enter correct plate text"
                      className="w-full px-4 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500 font-mono text-lg"
                    />
                  </div>
                  
                  <div>
                    <label className="block text-sm font-medium text-gray-700 mb-1">
                      Province
                    </label>
                    <div className="relative">
                      <Search className="absolute left-3 top-3 text-gray-400" size={18} />
                      <input
                        type="text"
                        value={searchProvince || correctedProvince}
                        onChange={(e) => {
                          setSearchProvince(e.target.value);
                          setCorrectedProvince(e.target.value);
                        }}
                        placeholder="Search province..."
                        className="w-full pl-10 pr-4 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500"
                      />
                    </div>
                    
                    {searchProvince && (
                      <div className="mt-2 max-h-48 overflow-y-auto border border-gray-300 rounded-lg">
                        {filteredProvinces.map(province => (
                          <div
                            key={province}
                            onClick={() => {
                              setCorrectedProvince(province);
                              setSearchProvince('');
                            }}
                            className="px-4 py-2 hover:bg-blue-50 cursor-pointer"
                          >
                            {province}
                          </div>
                        ))}
                      </div>
                    )}
                  </div>
                  
                  <button
                    onClick={() => handleVerify(false)}
                    disabled={submitting || !correctedText}
                    className="w-full px-4 py-3 bg-blue-600 hover:bg-blue-700 text-white rounded-lg font-semibold disabled:opacity-50 disabled:cursor-not-allowed"
                  >
                    {submitting ? 'Submitting...' : 'Submit Correction (MLPR)'}
                  </button>
                </div>
              </div>
            </div>
          ) : (
            <div className="bg-gray-50 rounded-lg p-12 text-center">
              <AlertCircle className="mx-auto text-gray-400 mb-3" size={48} />
              <p className="text-gray-600">Select a plate from the list to verify</p>
            </div>
          )}
        </div>
      </div>
    </div>
  );
};

export default Verification;
