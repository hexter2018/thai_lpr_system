/** @type {import('tailwindcss').Config} */
export default {
  content: [
    "./index.html",
    "./src/**/*.{js,jsx}"
  ],
  // เปิดใช้งาน Auto Dark Mode ตาม System OS
  darkMode: 'media', 
  theme: {
    extend: {
      colors: {
        // เพิ่มชุดสีสำหรับ Modern UI
        panel: {
          light: '#ffffff',
          dark: '#1e293b', // slate-800
        },
        page: {
          light: '#f8fafc', // slate-50
          dark: '#0f172a',  // slate-900
        }
      }
    },
  },
  plugins: [],
}