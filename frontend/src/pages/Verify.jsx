import { useEffect, useState } from 'react'


export default function Master() {
const [data, setData] = useState([])


useEffect(() => {
fetch("/api/master/all")
.then(res => res.json())
.then(data => setData(data))
}, [])


return (
<div>
<h2 className="text-xl font-semibold mb-2">📚 Master Plates</h2>
<table className="table-auto w-full border">
<thead>
<tr className="bg-gray-100">
<th>ID</th><th>Plate</th><th>Type</th><th>Confidence</th><th>Image</th>
</tr>
</thead>
<tbody>
{data.map(r => (
<tr key={r.id} className="text-sm">
<td>{r.id}</td>
<td>{r.full_plate}</td>
<td>{r.type}</td>
<td>{(r.confidence * 100).toFixed(1)}%</td>
<td><img src={`/${r.image_path}`} className="h-12" /></td>
</tr>
))}
</tbody>
</table>
</div>
)
}