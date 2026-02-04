import React from 'react'
import ReactDOM from 'react-dom/client'
import App from './App.jsx'
import './index.css'


ReactDOM.createRoot(document.getElementById('root')).render(
<React.StrictMode>
<App />
</React.StrictMode>
)




// Directory: alpr_frontend/src/App.jsx
import { BrowserRouter as Router, Routes, Route } from 'react-router-dom'
import Dashboard from './pages/Dashboard'
import Upload from './pages/Upload'
import Verify from './pages/Verify'
import Master from './pages/Master'


function App() {
return (
<Router>
<div className="p-4">
<h1 className="text-2xl font-bold mb-4">Thai ALPR Dashboard</h1>
<Routes>
<Route path="/" element={<Dashboard />} />
<Route path="/upload" element={<Upload />} />
<Route path="/verify" element={<Verify />} />
<Route path="/master" element={<Master />} />
</Routes>
</div>
</Router>
)
}


export default App