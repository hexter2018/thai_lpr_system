import { useState } from 'react'


export default function Upload() {
const [file, setFile] = useState()
const [result, setResult] = useState()


const handleUpload = async () => {
const form = new FormData()
form.append("file", file)


const res = await fetch("/api/upload/image", {
method: "POST",
body: form
})
const data = await res.json()
setResult(data)
}


return (
<div>
<h2 className="text-xl font-semibold mb-2">🖼️ Upload Image</h2>
<input type="file" onChange={e => setFile(e.target.files[0])} className="mb-2" />
<button onClick={handleUpload} className="bg-blue-600 text-white px-4 py-1 rounded">Upload</button>
{result && (
<div className="mt-4">
<img src={`/${result.image}`} alt="plate" className="h-32" />
<p>📄 Plate: <strong>{result.plate}</strong> ({Math.round(result.confidence * 100)}%)</p>
<p>📘 Type: {result.type}</p>
</div>
)}
</div>
)
}