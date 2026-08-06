import React, { useState } from "react";
import { createRoot } from "react-dom/client";
import { BrowserRouter, Link, Route, Routes } from "react-router-dom";
import {
  QueryClient,
  QueryClientProvider,
  useQuery,
} from "@tanstack/react-query";
import "./styles.css";

const api = import.meta.env.VITE_API_BASE_URL || "/api";
const request = (path: string, init: RequestInit = {}) => {
  const key = sessionStorage.getItem("adminApiKey");
  return fetch(api + path, {
    ...init,
    headers: {
      "Content-Type": "application/json",
      ...(key ? { Authorization: `Bearer ${key}` } : {}),
    },
  }).then(async (r) => {
    if (!r.ok) throw new Error(`${r.status}: ${await r.text()}`);
    return r.status === 204 ? null : r.json();
  });
};
const get = (path: string) => request(path);
function experienceLabel(experience: any) {
  if (!experience) return "-";
  if (experience.raw && /경력무관|경력 무관/.test(experience.raw))
    return "경력무관";
  if (experience.type === "NEWBIE") return "신입";
  if (experience.type === "ANY") return "신입/경력";
  if (experience.min_years != null && experience.max_years != null)
    return `경력 ${experience.min_years}~${experience.max_years}년`;
  if (experience.min_years != null)
    return `경력 ${experience.min_years}년 이상`;
  if (experience.type === "EXPERIENCED") return "경력";
  return experience.raw || "-";
}
function deadlineLabel(deadline: any) {
  if (!deadline?.date) return deadline?.always_open ? "상시채용" : "-";
  const days = Math.ceil((new Date(`${deadline.date}T23:59:59`).getTime() - Date.now()) / 86400000);
  return days < 0 ? "마감" : `D-${days} (${deadline.date})`;
}
function dateTimeLabel(value: string | null | undefined) {
  if (!value) return "-";
  return new Date(value).toLocaleString("ko-KR", { dateStyle: "short", timeStyle: "short" });
}
function Header() {
  return (
    <header>
      <Link to="/">Job Collector</Link>
      <nav>
        <Link to="/jobs">공고</Link>
        <Link to="/crawl-runs">수집 실행</Link>
        <Link to="/sources">출처</Link>
        <Link to="/profiles">프로필</Link>
        <Link to="/api-tester">API 테스트</Link>
        <Link to="/settings">설정</Link>
      </nav>
    </header>
  );
}
function Overview() {
  const { data, error } = useQuery({
    queryKey: ["summary"],
    queryFn: () => get("/v1/dashboard/summary"),
  });
  if (error) return <p>API 연결 오류</p>;
  const j = data?.jobs;
  const sources = data?.sources?.items || [];
  return (
    <>
      <h1>개요</h1>
      <section className="cards">
        {[
          ["전체 공고", j?.total],
          ["활성 공고", j?.active],
          ["최근 7일 신규", j?.new_last_7_days],
          ["상태 확인 불가", j?.unknown],
        ].map(([n, v]) => (
          <article key={String(n)}>
            <small>{n}</small>
            <strong>{v ?? "-"}</strong>
          </article>
        ))}
      </section>
      <section className="settings-card">
        <h2>출처별 현황</h2>
        <table>
          <thead>
            <tr>
              <th>출처</th>
              <th>수집 공고</th>
              <th>활성</th>
              <th>마감</th>
              <th>UNKNOWN</th>
              <th>최근 동기화</th>
              <th>상태</th>
            </tr>
          </thead>
          <tbody>
            {sources.map((source: any) => (
              <tr key={source.source}>
                <td>{source.source}</td>
                <td>{source.total}</td>
                <td>{source.active}</td>
                <td>{source.closed}</td>
                <td>{source.unknown}</td>
                <td>{dateTimeLabel(source.last_finished_at || source.last_started_at)}</td>
                <td>{source.enabled ? source.last_status || "대기" : "비활성"}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </section>
      <p>
        마지막 전체 동기화: {dateTimeLabel(data?.crawl?.last_finished_at || data?.crawl?.last_started_at)}
      </p>
    </>
  );
}
function Jobs() {
  const [q, setQ] = useState("");
  const [region, setRegion] = useState("");
  const [source, setSource] = useState("");
  const [experience, setExperience] = useState("");
  const [employment, setEmployment] = useState("");
  const [minYears, setMinYears] = useState("");
  const [includeUnknown, setIncludeUnknown] = useState(false);
  const [sortField, setSortField] = useState("deadline_date");
  const [sortDirection, setSortDirection] = useState("asc");
  const [cursor, setCursor] = useState("");
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const params = new URLSearchParams({
    statuses: "ACTIVE,CLOSED,UNKNOWN,DELETED",
    keyword: q,
    limit: "100",
    sort: `${sortField}:${sortDirection}`,
  });
  if (source) params.set("sources", source);
  if (region) params.set("region", region);
  params.set(
    "experience_types",
    experience ||
      (includeUnknown
        ? "NEWBIE,EXPERIENCED,ANY,UNKNOWN"
        : "NEWBIE,EXPERIENCED,ANY"),
  );
  if (employment) params.set("employment_types", employment);
  if (minYears) params.set("min_experience", minYears);
  if (cursor) params.set("cursor", cursor);
  const { data, isLoading } = useQuery({
    queryKey: [
      "jobs",
      q,
      source,
      region,
      experience,
      employment,
      minYears,
      includeUnknown,
      sortField,
      sortDirection,
      cursor,
    ],
    queryFn: () => get(`/v1/jobs?${params}`),
  });
  const { data: selectedJob, isLoading: detailLoading, error: detailError } = useQuery({
    queryKey: ["job-detail", selectedId],
    queryFn: () => get(`/v1/jobs/${selectedId}`),
    enabled: Boolean(selectedId),
  });
  const reset =
    (setter: (value: string) => void) =>
    (event: React.ChangeEvent<HTMLInputElement | HTMLSelectElement>) => {
      setter(event.target.value);
      setCursor("");
    };
  return (
    <>
      <h1>공고</h1>
      <section className="job-filters">
        <input
          placeholder="회사 또는 포지션 검색"
          value={q}
          onChange={reset(setQ)}
        />
        <select value={source} onChange={reset(setSource)}>
          <option value="">출처 전체</option>
          <option value="WANTED">WANTED</option>
          <option value="SARAMIN">SARAMIN</option>
          <option value="JOBKOREA">JOBKOREA</option><option value="SAMSUNG">SAMSUNG</option><option value="LG">LG</option><option value="HYUNDAI">HYUNDAI</option>
        </select>
        <input
          placeholder="지역 (예: 경기)"
          value={region}
          onChange={reset(setRegion)}
        />
        <select value={experience} onChange={reset(setExperience)}>
          <option value="">신입·경력 전체</option>
          <option value="NEWBIE">신입</option>
          <option value="EXPERIENCED">경력</option>
          <option value="ANY">신입·경력</option>
        </select>
        <select value={employment} onChange={reset(setEmployment)}>
          <option value="">고용 형태 전체</option>
          <option value="정규직">정규직</option>
          <option value="계약직">계약직</option>
          <option value="인턴">인턴</option>
        </select>
        <input
          type="number"
          min="0"
          placeholder="최소 경력(년)"
          value={minYears}
          onChange={reset(setMinYears)}
        />
        <select value={sortField} onChange={reset(setSortField)}>
          <option value="deadline_date">마감일순</option>
          <option value="company_name">회사명순</option>
          <option value="title">포지션순</option>
          <option value="source">출처순</option>
          <option value="region">지역순</option>
          <option value="experience">경력순</option>
          <option value="employment_type">고용 형태순</option>
          <option value="updated_at">업데이트순</option>
          <option value="first_seen_at">등록순</option>
        </select>
        <select value={sortDirection} onChange={reset(setSortDirection)}>
          <option value="asc">오름차순</option>
          <option value="desc">내림차순</option>
        </select>
      </section>
      <div className="job-options">
        <label>
          <input
            type="checkbox"
            checked={includeUnknown}
            onChange={(event) => {
              setIncludeUnknown(event.target.checked);
              setCursor("");
            }}
          />{" "}
          UNKNOWN 경력 포함
        </label>
      </div>
      {isLoading ? (
        <p>불러오는 중…</p>
      ) : (
        <>
          <p>{data?.items.length ?? 0}건 표시</p>
          <table>
            <thead>
              <tr>
                <th>회사</th>
                <th>포지션</th>
                <th>출처</th>
                <th>상태</th>
                <th>지역</th>
                <th>경력</th>
                <th>고용 형태</th>
                <th>마감일</th>
              </tr>
            </thead>
            <tbody>
              {data?.items.map((x: any) => (
                <tr key={x.id}>
                  <td>{x.company_name}</td>
                  <td>
                    <button className="job-title" onClick={() => setSelectedId(x.id)}>
                      {x.title}
                    </button>
                  </td>
                  <td>{x.source}</td>
                  <td>
                    <span className={"badge " + x.effective_status}>
                      {x.effective_status}
                    </span>
                  </td>
                  <td>{x.region || x.location_raw || "-"}</td>
                  <td>
                    {experienceLabel(x.experience)}
                  </td>
                  <td>{x.employment_type || "-"}</td>
                  <td>{deadlineLabel(x.deadline)}</td>
                </tr>
              ))}
            </tbody>
          </table>
          {data?.page?.next_cursor && (
            <button onClick={() => setCursor(data.page.next_cursor)}>
              다음 100건 불러오기
            </button>
          )}
        </>
      )}
      {selectedId && (
        <div className="modal-backdrop" onClick={() => setSelectedId(null)}>
          <section className="job-modal" onClick={(event) => event.stopPropagation()}>
            <button className="modal-close" onClick={() => setSelectedId(null)} aria-label="닫기">
              ×
            </button>
            {detailLoading && <p>상세 정보를 불러오는 중…</p>}
            {detailError && <p>상세 정보를 불러오지 못했습니다.</p>}
            {selectedJob && (
              <>
                <small>{selectedJob.source}</small>
                <h2>{selectedJob.title}</h2>
                <p className="job-company">{selectedJob.company_name}</p>
                <dl className="job-detail-meta">
                  <dt>상태</dt><dd>{selectedJob.effective_status}</dd>
                  <dt>지역</dt><dd>{selectedJob.region || selectedJob.location_raw || "-"}</dd>
                  <dt>경력</dt><dd>{experienceLabel(selectedJob.experience)}</dd>
                  <dt>고용 형태</dt><dd>{selectedJob.employment_type || "-"}</dd>
                  <dt>마감일</dt><dd>{deadlineLabel(selectedJob.deadline)}</dd>
                </dl>
                <DetailList title="주요 업무" items={selectedJob.responsibilities} />
                <DetailList title="자격 요건" items={selectedJob.requirements} />
                <DetailList title="우대 사항" items={selectedJob.preferred_qualifications} />
                <button
                  onClick={() => window.open(selectedJob.url, "_blank", "noopener,noreferrer")}
                >
                  공고 확인
                </button>
              </>
            )}
          </section>
        </div>
      )}
    </>
  );
}
function DetailList({ title, items }: { title: string; items?: string[] }) {
  if (!items?.length) return null;
  return (
    <section className="job-detail-section">
      <h3>{title}</h3>
      <ul>{items.map((item, index) => <li key={`${title}-${index}`}>{item}</li>)}</ul>
    </section>
  );
}
function Simple({ path, title }: { path: string; title: string }) {
  const { data } = useQuery({ queryKey: [path], queryFn: () => get(path) });
  return (
    <>
      <h1>{title}</h1>
      <pre>{JSON.stringify(data, null, 2)}</pre>
    </>
  );
}
type Profile = {
  id: string;
  display_name: string;
  queries: string[];
  include_keywords: string[];
  exclude_keywords: string[];
  source_queries: Record<string, string[]>;
  company_queries?: Record<string, string[]>;
};
const blank: Profile = {
  id: "",
  display_name: "",
  queries: [],
  include_keywords: [],
  exclude_keywords: [],
  source_queries: { WANTED: [] },
  company_queries: { WANTED: [] },
};
/**
 * Keep the editor state complete even when an older API response does not
 * contain fields that were added later (such as company_queries).
 */
const normalizeProfile = (profile: Partial<Profile>): Profile => ({
  id: profile.id || "",
  display_name: profile.display_name || "",
  queries: profile.queries || [],
  include_keywords: profile.include_keywords || [],
  exclude_keywords: profile.exclude_keywords || [],
  source_queries: profile.source_queries || {},
  company_queries: profile.company_queries || {},
});
const lines = (value: string) =>
  value
    .split("\n")
    .map((x) => x.trim())
    .filter(Boolean);
function Profiles() {
  const { data, error, refetch } = useQuery<{ items: Profile[] }>({
    queryKey: ["profiles"],
    queryFn: () => get("/v1/profiles"),
  });
  const [form, setForm] = useState<Profile>(blank);
  const [editing, setEditing] = useState(false);
  const [message, setMessage] = useState("");
  const field = (name: keyof Profile) =>
    Array.isArray(form[name]) ? (form[name] as string[]).join("\n") : "";
  const setLines = (name: keyof Profile, value: string) =>
    setForm({ ...form, [name]: lines(value) });
  const companyField = (source: string, label: string) => (
    <label>
      {label} 회사명·영문명·약칭 (한 줄에 하나)
      <textarea
        placeholder="예: 현대모비스\nHyundai Mobis"
        value={(form.company_queries?.[source] || []).join("\n")}
        onChange={(e) =>
          setForm({
            ...form,
            company_queries: {
              ...(form.company_queries || {}),
              [source]: lines(e.target.value),
            },
          })
        }
      />
    </label>
  );
  const save = async () => {
    try {
      // Always send the complete profile shape. This prevents company queries
      // from being dropped when editing profiles created before that field
      // existed or when the response is missing optional keys.
      const payload = normalizeProfile(form);
      await request(
        editing ? `/v1/admin/profiles/${payload.id}` : "/v1/admin/profiles",
        { method: editing ? "PUT" : "POST", body: JSON.stringify(payload) },
      );
      setMessage("저장되었습니다.");
      setForm(blank);
      setEditing(false);
      refetch();
    } catch (e) {
      setMessage(`저장 실패: ${String(e)}`);
    }
  };
  const remove = async (p: Profile) => {
    if (!confirm(`${p.display_name} 프로필을 삭제할까요?`)) return;
    try {
      await request(`/v1/admin/profiles/${p.id}`, { method: "DELETE" });
      refetch();
    } catch (e) {
      setMessage(`삭제 실패: ${String(e)}`);
    }
  };
  return (
    <>
      <h1>검색 프로필</h1>
      <p>관리자 API 키를 설정한 뒤 프로필을 추가·수정·삭제할 수 있습니다.</p>
      {error && <p>프로필을 불러올 수 없습니다.</p>}
      <section className="profile-grid">
        {data?.items.map((p) => (
          <article key={p.id}>
            <strong>{p.display_name}</strong>
            <small>{p.id}</small>
            <p>{p.queries.join(", ")}</p>
            <button
              onClick={() => {
                setForm(normalizeProfile(p));
                setEditing(true);
              }}
            >
              수정
            </button>
            <button className="danger" onClick={() => remove(p)}>
              삭제
            </button>
          </article>
        ))}
      </section>
      <h2>{editing ? "프로필 수정" : "프로필 추가"}</h2>
      <section className="profile-form">
        <input
          placeholder="ID (예: automotive_security)"
          value={form.id}
          disabled={editing}
          onChange={(e) => setForm({ ...form, id: e.target.value })}
        />
        <input
          placeholder="표시 이름"
          value={form.display_name}
          onChange={(e) => setForm({ ...form, display_name: e.target.value })}
        />
        <label>
          검색어 (한 줄에 하나)
          <textarea
            value={field("queries")}
            onChange={(e) => setLines("queries", e.target.value)}
          />
        </label>
        <label>
          포함 키워드 (한 줄에 하나)
          <textarea
            value={field("include_keywords")}
            onChange={(e) => setLines("include_keywords", e.target.value)}
          />
        </label>
        <label>
          제외 키워드 (한 줄에 하나)
          <textarea
            value={field("exclude_keywords")}
            onChange={(e) => setLines("exclude_keywords", e.target.value)}
          />
        </label>
        <label>
          원티드 전용 검색어 (한 줄에 하나)
          <textarea
            value={(form.source_queries.WANTED || []).join("\n")}
            onChange={(e) =>
              setForm({
                ...form,
                source_queries: {
                  ...form.source_queries,
                  WANTED: lines(e.target.value),
                },
              })
            }
          />
        </label>
        <label>
          관심 회사명·영문명·약칭 (한 줄에 하나)
          <textarea
            placeholder="예: 스트라드비젼\nStradVision\n포티투닷\n42dot"
            value={(form.company_queries?.WANTED || []).join("\n")}
            onChange={(e) =>
              setForm({
                ...form,
                company_queries: {
                  ...(form.company_queries || {}),
                  WANTED: lines(e.target.value),
                },
              })
            }
          />
        </label>
        {companyField("SARAMIN", "사람인")}
        {companyField("JOBKOREA", "잡코리아")}
        {companyField("SAMSUNG", "삼성 Careers")}
        {companyField("LG", "LG Careers")}
        {companyField("HYUNDAI", "현대 Careers")}
        <button
          onClick={save}
          disabled={!form.id || !form.display_name || !form.queries.length}
        >
          저장
        </button>
        {editing && (
          <button
            onClick={() => {
              setEditing(false);
              setForm(blank);
            }}
          >
            취소
          </button>
        )}
        <p>{message}</p>
      </section>
    </>
  );
}
type ApiEndpoint = {
  name: string;
  method: "GET" | "POST" | "PUT" | "DELETE";
  path: string;
  body?: string;
  admin?: boolean;
};
const endpoints: ApiEndpoint[] = [
  { name: "프로세스 상태", method: "GET", path: "/health" },
  { name: "준비 상태", method: "GET", path: "/ready" },
  {
    name: "공고 목록",
    method: "GET",
    path: "/v1/jobs?statuses=ACTIVE&limit=20",
  },
  { name: "공고 상세", method: "GET", path: "/v1/jobs/{job_id}" },
  { name: "공고 변경 이력", method: "GET", path: "/v1/jobs/{job_id}/changes" },
  { name: "출처 목록", method: "GET", path: "/v1/sources" },
  { name: "프로필 목록", method: "GET", path: "/v1/profiles" },
  { name: "프로필 상세", method: "GET", path: "/v1/profiles/{profile_id}" },
  { name: "대시보드 요약", method: "GET", path: "/v1/dashboard/summary" },
  {
    name: "전체 동기화",
    method: "POST",
    path: "/v1/admin/sync",
    body: '{\n  "profile": "mobility_sdv_security_cpp",\n  "mode": "incremental"\n}',
    admin: true,
  },
  {
    name: "원티드 동기화",
    method: "POST",
    path: "/v1/admin/sources/WANTED/sync",
    body: '{\n  "profile": "mobility_sdv_security_cpp",\n  "mode": "incremental"\n}',
    admin: true,
  },
  {
    name: "사람인 동기화",
    method: "POST",
    path: "/v1/admin/sources/SARAMIN/sync",
    body: '{\n  "profile": "mobility_sdv_security_cpp",\n  "mode": "incremental"\n}',
    admin: true,
  },
  {
    name: "잡코리아 동기화",
    method: "POST",
    path: "/v1/admin/sources/JOBKOREA/sync",
    body: '{\n  "profile": "mobility_sdv_security_cpp",\n  "mode": "incremental"\n}',
    admin: true,
  },
  {
    name: "삼성 Careers 동기화",
    method: "POST",
    path: "/v1/admin/sources/SAMSUNG/sync",
    body: '{\n  "profile": "mobility_sdv_security_cpp",\n  "mode": "incremental"\n}',
    admin: true,
  },
  {
    name: "LG Careers 동기화",
    method: "POST",
    path: "/v1/admin/sources/LG/sync",
    body: '{\n  "profile": "mobility_sdv_security_cpp",\n  "mode": "incremental"\n}',
    admin: true,
  },
  {
    name: "현대 Careers 동기화",
    method: "POST",
    path: "/v1/admin/sources/HYUNDAI/sync",
    body: '{\n  "profile": "mobility_sdv_security_cpp",\n  "mode": "incremental"\n}',
    admin: true,
  },
  {
    name: "특정 공고 재수집",
    method: "POST",
    path: "/v1/admin/jobs/{job_id}/recheck",
    body: "{}",
    admin: true,
  },
  {
    name: "프로필 다시 로드",
    method: "POST",
    path: "/v1/admin/profiles/reload",
    body: "{}",
    admin: true,
  },
  {
    name: "수집 일정 조회",
    method: "GET",
    path: "/v1/admin/settings/schedule",
    admin: true,
  },
  {
    name: "수집 일정 저장",
    method: "PUT",
    path: "/v1/admin/settings/schedule",
    body: '{\n  "sync_cron": "0 2 * * *",\n  "recheck_cron": "0 3 * * *"\n}',
    admin: true,
  },
  {
    name: "전체 공고 삭제",
    method: "DELETE",
    path: "/v1/admin/jobs",
    body: '{\n  "confirm": "DELETE_ALL"\n}',
    admin: true,
  },
  {
    name: "수집 실행 목록",
    method: "GET",
    path: "/v1/admin/crawl-runs",
    admin: true,
  },
  {
    name: "수집 실행 상세",
    method: "GET",
    path: "/v1/admin/crawl-runs/{run_id}",
    admin: true,
  },
];
function ApiTester() {
  const [selected, setSelected] = useState(0);
  const [path, setPath] = useState(endpoints[0].path);
  const [body, setBody] = useState(endpoints[0].body || "");
  const [result, setResult] = useState("아직 요청하지 않았습니다.");
  const [loading, setLoading] = useState(false);
  const choose = (index: number) => {
    setSelected(index);
    setPath(endpoints[index].path);
    setBody(endpoints[index].body || "");
    setResult("아직 요청하지 않았습니다.");
  };
  const run = async () => {
    const endpoint = endpoints[selected];
    if (path.includes("{")) {
      setResult(
        "경로의 {job_id}, {profile_id}, {run_id}를 실제 값으로 바꿔주세요.",
      );
      return;
    }
    if (endpoint.admin && !sessionStorage.getItem("adminApiKey")) {
      setResult("관리자 API 키가 없습니다. 설정 화면에서 먼저 저장하세요.");
      return;
    }
    try {
      setLoading(true);
      const started = performance.now();
      const direct = path === "/health" || path === "/ready";
      const url =
        direct && api.startsWith("http")
          ? `${new URL(api).origin}${path}`
          : direct
            ? path
            : api + path;
      const response = await fetch(url, {
        method: endpoint.method,
        headers: {
          "Content-Type": "application/json",
          ...(endpoint.admin
            ? {
                Authorization: `Bearer ${sessionStorage.getItem("adminApiKey")}`,
              }
            : {}),
        },
        ...(endpoint.method === "GET" || endpoint.method === "DELETE"
          ? {}
          : { body }),
      });
      const text = await response.text();
      const elapsed = Math.round(performance.now() - started);
      let output: unknown = text;
      try {
        output = text ? JSON.parse(text) : null;
      } catch {
        /* retain text */
      }
      setResult(
        JSON.stringify(
          {
            status: response.status,
            ok: response.ok,
            duration_ms: elapsed,
            response: output,
          },
          null,
          2,
        ),
      );
    } catch (error) {
      setResult(JSON.stringify({ error: String(error) }, null, 2));
    } finally {
      setLoading(false);
    }
  };
  return (
    <>
      <h1>API 테스트</h1>
      <p>
        등록된 API를 선택하고 실행 결과를 확인합니다. 관리자 API는 설정에 저장한
        세션 키를 사용하며, 동기화 요청은 실제 수집을 시작합니다.
      </p>
      <section className="api-tester">
        <label>
          API 선택
          <select
            value={selected}
            onChange={(e) => choose(Number(e.target.value))}
          >
            {endpoints.map((item, index) => (
              <option key={item.name} value={index}>
                {item.method} · {item.name}
                {item.admin ? " (관리자)" : ""}
              </option>
            ))}
          </select>
        </label>
        <label>
          경로
          <input value={path} onChange={(e) => setPath(e.target.value)} />
        </label>
        {endpoints[selected].method !== "GET" && (
          <label>
            JSON 요청 본문
            <textarea value={body} onChange={(e) => setBody(e.target.value)} />
          </label>
        )}
        <button onClick={run} disabled={loading}>
          {loading ? "요청 중…" : `${endpoints[selected].method} 요청 실행`}
        </button>
        <h2>결과</h2>
        <pre className="api-result">{result}</pre>
      </section>
    </>
  );
}
function Settings() {
  const [key, setKey] = useState(sessionStorage.getItem("adminApiKey") || "");
  const [syncCron, setSyncCron] = useState("0 2 * * *");
  const [recheckCron, setRecheckCron] = useState("0 3 * * *");
  const [randomDelayEnabled, setRandomDelayEnabled] = useState(false);
  const [randomDelayMax, setRandomDelayMax] = useState("0.5");
  const [confirmText, setConfirmText] = useState("");
  const [message, setMessage] = useState("");
  const saveKey = () => {
    sessionStorage.setItem("adminApiKey", key);
    setMessage("관리자 API 키를 저장했습니다.");
  };
  const loadSchedule = async () => {
    try {
      const data = await request("/v1/admin/settings/schedule");
      setSyncCron(data.sync_cron);
      setRecheckCron(data.recheck_cron);
      setMessage("현재 일정을 불러왔습니다.");
    } catch (error) {
      setMessage(`일정 조회 실패: ${String(error)}`);
    }
  };
  const loadRequestPacing = async () => {
    try {
      const data = await request("/v1/admin/settings/request-pacing");
      setRandomDelayEnabled(Boolean(data.random_delay_enabled));
      setRandomDelayMax(String(data.random_delay_max_seconds));
      setMessage("요청 지연 설정을 불러왔습니다.");
    } catch (error) {
      setMessage(`요청 지연 설정 조회 실패: ${String(error)}`);
    }
  };
  const saveSchedule = async () => {
    try {
      await request("/v1/admin/settings/schedule", {
        method: "PUT",
        body: JSON.stringify({
          sync_cron: syncCron,
          recheck_cron: recheckCron,
        }),
      });
      setMessage(
        "일정을 저장했습니다. Scheduler는 최대 30초 안에 새 설정을 반영합니다.",
      );
    } catch (error) {
      setMessage(`일정 저장 실패: ${String(error)}`);
    }
  };
  const saveRequestPacing = async () => {
    try {
      await request("/v1/admin/settings/request-pacing", {
        method: "PUT",
        body: JSON.stringify({
          random_delay_enabled: randomDelayEnabled,
          random_delay_max_seconds: Number(randomDelayMax),
        }),
      });
      setMessage("요청 지연 설정을 저장했고 즉시 적용했습니다.");
    } catch (error) {
      setMessage(`요청 지연 설정 저장 실패: ${String(error)}`);
    }
  };
  const requestTorNewnym = async () => {
    try {
      await request("/v1/admin/tor/newnym", { method: "POST" });
      setMessage("Tor에 새 회선을 요청했습니다. 진행 중인 요청은 재시도하지 않습니다.");
    } catch (error) {
      setMessage(`Tor 새 회선 요청 실패: ${String(error)}`);
    }
  };
  const deleteAll = async () => {
    if (confirmText !== "DELETE_ALL") return;
    try {
      const data = await request("/v1/admin/jobs", {
        method: "DELETE",
        body: JSON.stringify({ confirm: "DELETE_ALL" }),
      });
      setConfirmText("");
      setMessage(
        `공고 ${data.deleted_jobs}개와 변경 이력 ${data.deleted_snapshots}개를 삭제했습니다.`,
      );
    } catch (error) {
      setMessage(`전체 삭제 실패: ${String(error)}`);
    }
  };
  return (
    <>
      <h1>설정</h1>
      <section className="settings-card">
        <h2>관리자 인증</h2>
        <p>관리자 API 키는 이 브라우저 세션에만 저장됩니다.</p>
        <input
          type="password"
          value={key}
          onChange={(e) => setKey(e.target.value)}
          placeholder="관리자 API 키"
        />
        <button onClick={saveKey}>키 저장</button>
      </section>
      <section className="settings-card">
        <h2>수집 일정</h2>
        <p>
          Cron 형식: 분 시 일 월 요일. 예: <code>0 2 * * *</code>는 매일
          02:00입니다.
        </p>
        <label>
          검색 프로필 동기화
          <input
            value={syncCron}
            onChange={(e) => setSyncCron(e.target.value)}
          />
        </label>
        <label>
          기존 공고 재확인
          <input
            value={recheckCron}
            onChange={(e) => setRecheckCron(e.target.value)}
          />
        </label>
        <button onClick={loadSchedule}>현재 일정 불러오기</button>
        <button onClick={saveSchedule}>일정 저장</button>
      </section>
      <section className="settings-card">
        <h2>요청 속도 제한</h2>
        <p>
          기본 지연 시간에 0초부터 최대값 사이의 무작위 지연을 추가합니다.
          저장 즉시 실행 중인 수집에도 적용됩니다.
        </p>
        <label>
          <input
            type="checkbox"
            checked={randomDelayEnabled}
            onChange={(e) => setRandomDelayEnabled(e.target.checked)}
          />{" "}
          랜덤 지연 활성화
        </label>
        <label>
          랜덤 지연 최대(초)
          <input
            type="number"
            min="0"
            max="60"
            step="0.1"
            value={randomDelayMax}
            onChange={(e) => setRandomDelayMax(e.target.value)}
          />
        </label>
        <button onClick={loadRequestPacing}>현재 설정 불러오기</button>
        <button onClick={saveRequestPacing}>요청 지연 설정 저장</button>
      </section>
      <section className="settings-card">
        <h2>Tor 프록시</h2>
        <p>
          Tor 사용 여부와 ControlPort는 환경변수로 설정합니다. 아래 버튼은
          관리자용 수동 회선 변경 요청이며 차단 요청을 자동 재시도하지 않습니다.
        </p>
        <button onClick={requestTorNewnym}>새 Tor 회선 요청</button>
      </section>
      <section className="settings-card danger-zone">
        <h2>수집 공고 전체 삭제</h2>
        <p>
          공고와 변경 이력만 삭제합니다. 수집 실행 이력과 프로필은 유지됩니다.
          계속하려면 정확히 <code>DELETE_ALL</code>을 입력하세요.
        </p>
        <input
          value={confirmText}
          onChange={(e) => setConfirmText(e.target.value)}
          placeholder="DELETE_ALL"
        />
        <button
          className="danger"
          onClick={deleteAll}
          disabled={confirmText !== "DELETE_ALL"}
        >
          공고 전체 삭제
        </button>
      </section>
      <p>{message}</p>
    </>
  );
}
function App() {
  return (
    <>
      <Header />
      <main>
        <Routes>
          <Route path="/" element={<Overview />} />
          <Route path="/jobs" element={<Jobs />} />
          <Route
            path="/crawl-runs"
            element={<Simple title="수집 실행" path="/v1/admin/crawl-runs" />}
          />
          <Route
            path="/sources"
            element={<Simple title="출처" path="/v1/sources" />}
          />
          <Route path="/profiles" element={<Profiles />} />
          <Route path="/api-tester" element={<ApiTester />} />
          <Route path="/settings" element={<Settings />} />
        </Routes>
      </main>
    </>
  );
}
createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <QueryClientProvider client={new QueryClient()}>
      <BrowserRouter>
        <App />
      </BrowserRouter>
    </QueryClientProvider>
  </React.StrictMode>,
);
