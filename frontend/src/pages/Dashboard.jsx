import { useEffect, useState } from 'react'


export default function Dashboard() {
const [summary, setSummary] = useState({})


useEffect(() => {
fetch("/api/master/summary")
.then(res => res.json())
.then(data => setSummary(data))
}, [])


return (
<div>
<h2 className="text-xl font-semibold mb-2">📊 KPI Overview</h2>
<ul className="list-disc ml-5">
<li>Total Plates: {summary.total}</li>
<li>ALPR %: {summary.alpr_percent}%</li>
<li>MLPR %: {summary.mlpr_percent}%</li>
<li>Top Provinces: {summary.top_provinces?.join(', ')}</li>
</ul>
</div>
)
}