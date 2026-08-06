import React, { useState } from 'react';
import { createRoot } from 'react-dom/client';
import { BrowserRouter, Link, Route, Routes } from 'react-router-dom';
import { QueryClient, QueryClientProvider, useQuery } from '@tanstack/react-query';
import './styles.css';

const api = import.meta.env.VITE_API_BASE_URL || '/api';
const request = (path: string, init: RequestInit = {}) => {
  const key = sessionStorage.getItem('adminApiKey');
  return fetch(api + path, { ...init, headers: { 'Content-Type': 'application/json', ...(key ? { Authorization: `Bearer ${key}` } : {}) } }).then(async r => {
    if (!r.ok) throw new Error(`${r.status}: ${await r.text()}`);
    return r.status === 204 ? null : r.json();
  });
};
const get = (path: string) => request(path);
function Header() { return <header><Link to="/">Job Collector</Link><nav><Link to="/jobs">공고</Link><Link to="/crawl-runs">수집 실행</Link><Link to="/sources">출처</Link><Link to="/profiles">프로필</Link><Link to="/settings">설정</Link></nav></header>; }
function Overview() { const { data, error } = useQuery({ queryKey: ['summary'], queryFn: () => get('/v1/dashboard/summary') }); if (error) return <p>API 연결 오류</p>; const j = data?.jobs; return <><h1>개요</h1><section className="cards">{[['전체 공고', j?.total], ['활성 공고', j?.active], ['최근 7일 신규', j?.new_last_7_days], ['상태 확인 불가', j?.unknown]].map(([n, v]) => <article key={String(n)}><small>{n}</small><strong>{v ?? '-'}</strong></article>)}</section></>; }
function Jobs() { const [q, setQ] = useState(''); const { data, isLoading } = useQuery({ queryKey: ['jobs', q], queryFn: () => get(`/v1/jobs?keyword=${encodeURIComponent(q)}`) }); return <><h1>공고</h1><input placeholder="회사 또는 포지션 검색" value={q} onChange={e => setQ(e.target.value)} />{isLoading ? <p>불러오는 중…</p> : <table><thead><tr><th>회사</th><th>포지션</th><th>출처</th><th>상태</th></tr></thead><tbody>{data?.items.map((x: any) => <tr key={x.id}><td>{x.company_name}</td><td><a href={x.url} target="_blank">{x.title}</a></td><td>{x.source}</td><td><span className={'badge ' + x.effective_status}>{x.effective_status}</span></td></tr>)}</tbody></table>}</>; }
function Simple({ path, title }: { path: string; title: string }) { const { data } = useQuery({ queryKey: [path], queryFn: () => get(path) }); return <><h1>{title}</h1><pre>{JSON.stringify(data, null, 2)}</pre></>; }
type Profile = { id: string; display_name: string; queries: string[]; include_keywords: string[]; exclude_keywords: string[]; source_queries: Record<string, string[]> };
const blank: Profile = { id: '', display_name: '', queries: [], include_keywords: [], exclude_keywords: [], source_queries: { WANTED: [] } };
const lines = (value: string) => value.split('\n').map(x => x.trim()).filter(Boolean);
function Profiles() {
  const { data, error, refetch } = useQuery<{ items: Profile[] }>({ queryKey: ['profiles'], queryFn: () => get('/v1/profiles') });
  const [form, setForm] = useState<Profile>(blank); const [editing, setEditing] = useState(false); const [message, setMessage] = useState('');
  const field = (name: keyof Profile) => Array.isArray(form[name]) ? (form[name] as string[]).join('\n') : '';
  const setLines = (name: keyof Profile, value: string) => setForm({ ...form, [name]: lines(value) });
  const save = async () => { try { await request(editing ? `/v1/admin/profiles/${form.id}` : '/v1/admin/profiles', { method: editing ? 'PUT' : 'POST', body: JSON.stringify(form) }); setMessage('저장되었습니다.'); setForm(blank); setEditing(false); refetch(); } catch (e) { setMessage(`저장 실패: ${String(e)}`); } };
  const remove = async (p: Profile) => { if (!confirm(`${p.display_name} 프로필을 삭제할까요?`)) return; try { await request(`/v1/admin/profiles/${p.id}`, { method: 'DELETE' }); refetch(); } catch (e) { setMessage(`삭제 실패: ${String(e)}`); } };
  return <><h1>검색 프로필</h1><p>관리자 API 키를 설정한 뒤 프로필을 추가·수정·삭제할 수 있습니다.</p>{error && <p>프로필을 불러올 수 없습니다.</p>}<section className="profile-grid">{data?.items.map(p => <article key={p.id}><strong>{p.display_name}</strong><small>{p.id}</small><p>{p.queries.join(', ')}</p><button onClick={() => { setForm(p); setEditing(true); }}>수정</button><button className="danger" onClick={() => remove(p)}>삭제</button></article>)}</section><h2>{editing ? '프로필 수정' : '프로필 추가'}</h2><section className="profile-form"><input placeholder="ID (예: automotive_security)" value={form.id} disabled={editing} onChange={e => setForm({ ...form, id: e.target.value })} /><input placeholder="표시 이름" value={form.display_name} onChange={e => setForm({ ...form, display_name: e.target.value })} /><label>검색어 (한 줄에 하나)<textarea value={field('queries')} onChange={e => setLines('queries', e.target.value)} /></label><label>포함 키워드 (한 줄에 하나)<textarea value={field('include_keywords')} onChange={e => setLines('include_keywords', e.target.value)} /></label><label>제외 키워드 (한 줄에 하나)<textarea value={field('exclude_keywords')} onChange={e => setLines('exclude_keywords', e.target.value)} /></label><label>원티드 전용 검색어 (한 줄에 하나)<textarea value={(form.source_queries.WANTED || []).join('\n')} onChange={e => setForm({ ...form, source_queries: { ...form.source_queries, WANTED: lines(e.target.value) } })} /></label><button onClick={save} disabled={!form.id || !form.display_name || !form.queries.length}>저장</button>{editing && <button onClick={() => { setEditing(false); setForm(blank); }}>취소</button>}<p>{message}</p></section></>;
}
function Settings() { const [key, setKey] = useState(sessionStorage.getItem('adminApiKey') || ''); return <><h1>설정</h1><p>관리자 API 키는 이 브라우저 세션에만 저장됩니다.</p><input type="password" value={key} onChange={e => setKey(e.target.value)} placeholder="관리자 API 키" /><button onClick={() => sessionStorage.setItem('adminApiKey', key)}>저장</button></>; }
function App() { return <><Header /><main><Routes><Route path="/" element={<Overview />} /><Route path="/jobs" element={<Jobs />} /><Route path="/crawl-runs" element={<Simple title="수집 실행" path="/v1/admin/crawl-runs" />} /><Route path="/sources" element={<Simple title="출처" path="/v1/sources" />} /><Route path="/profiles" element={<Profiles />} /><Route path="/settings" element={<Settings />} /></Routes></main></>; }
createRoot(document.getElementById('root')!).render(<React.StrictMode><QueryClientProvider client={new QueryClient()}><BrowserRouter><App /></BrowserRouter></QueryClientProvider></React.StrictMode>);
