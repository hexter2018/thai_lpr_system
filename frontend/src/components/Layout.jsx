import React from 'react';
import { Link, useLocation } from 'react-router-dom';
import { 
  LayoutDashboard, 
  Camera, 
  Radio, 
  CheckCircle, 
  BarChart3, 
  History 
} from 'lucide-react';

const Layout = ({ children }) => {
  const location = useLocation();
  
  const navItems = [
    { path: '/dashboard', icon: LayoutDashboard, label: 'Dashboard' },
    { path: '/cameras', icon: Camera, label: 'Cameras' },
    { path: '/live', icon: Radio, label: 'Live Monitor' },
    { path: '/verification', icon: CheckCircle, label: 'Verification' },
    { path: '/analytics', icon: BarChart3, label: 'Analytics' },
    { path: '/tracks', icon: History, label: 'Track History' }
  ];
  
  return (
    <div className="min-h-screen bg-gray-50">
      {/* Sidebar */}
      <aside className="fixed left-0 top-0 h-full w-64 bg-gray-900 text-white">
        <div className="p-6 border-b border-gray-800">
          <h1 className="text-2xl font-bold">Thai LPR V2</h1>
          <p className="text-sm text-gray-400 mt-1">License Plate Recognition</p>
        </div>
        
        <nav className="p-4">
          {navItems.map(item => {
            const Icon = item.icon;
            const isActive = location.pathname.startsWith(item.path);
            
            return (
              <Link
                key={item.path}
                to={item.path}
                className={`flex items-center gap-3 px-4 py-3 rounded-lg mb-2 transition-colors ${
                  isActive 
                    ? 'bg-blue-600 text-white' 
                    : 'text-gray-300 hover:bg-gray-800'
                }`}
              >
                <Icon size={20} />
                <span>{item.label}</span>
              </Link>
            );
          })}
        </nav>
      </aside>
      
      {/* Main content */}
      <main className="ml-64 p-8">
        {children}
      </main>
    </div>
  );
};

export default Layout;
