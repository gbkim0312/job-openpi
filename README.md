# Job Collector

원티드 등 채용 출처의 공고를 공통 형식으로 수집해 PostgreSQL에 저장하고, OpenAPI 및 관리자 대시보드로 제공하는 독립 서비스입니다. 조회 API는 외부 출처를 호출하지 않고 저장된 데이터만 반환합니다.

## 실행

```sh
cp .env.example .env
# ADMIN_API_KEY와 POSTGRES_PASSWORD를 안전한 값으로 변경
docker compose up --build
```

대시보드는 `http://localhost:8080`, OpenAPI 문서는 `http://localhost:8080/docs`에서 볼 수 있습니다. 개발 중 API 포트가 필요하면 compose의 `api` 서비스에 `8000:8000` 포트를 추가하세요.

### 미리 빌드한 이미지로 실행

소스 빌드 없이 로컬 이미지를 사용하려면 다음을 실행합니다.

```sh
docker build -t job-collector-backend:local ./backend
docker build -t job-collector-dashboard:local ./dashboard
cp .env.example .env
# .env의 POSTGRES_PASSWORD와 ADMIN_API_KEY를 변경
docker compose --env-file .env -f compose.images.yml up -d
```

`BACKEND_IMAGE`, `DASHBOARD_IMAGE`에 레지스트리 이미지 태그를 넣으면 같은 Compose 파일로 원격 이미지도 실행할 수 있습니다. 이 구성은 `build:`를 사용하지 않으며 API는 외부 포트를 열지 않고 대시보드만 `${DASHBOARD_PORT}`로 공개합니다.

## API 문서

실행 중인 서버의 자동 생성 문서는 다음 주소에서 제공합니다.

- Swagger UI: `http://localhost:8000/docs`
- ReDoc: `http://localhost:8000/redoc`
- OpenAPI JSON: `http://localhost:8000/openapi.json`

대시보드 Nginx 프록시를 통한다면 각각 `http://localhost:8080/docs`, `/redoc`, `/openapi.json`입니다. 모든 비관리자 API는 저장된 데이터만 읽으며 채용 출처에 직접 요청하지 않습니다.

### 공통 규칙

- 모든 비상태 API는 `/api/v1`로 시작합니다.
- 시간은 ISO 8601 UTC 형식입니다.
- 기본 공고 목록은 `ACTIVE` 공고만 20개 반환합니다.
- 쉼표로 여러 필터 값을 지정합니다. 예: `statuses=ACTIVE,UNKNOWN`.
- 목록 응답의 `page.next_cursor`를 다음 요청의 `cursor`로 전달합니다.

### 상태와 인증

`/api/v1/admin/*`는 관리자 키가 필요합니다. 키는 요청 헤더로만 전달합니다.

```http
Authorization: Bearer ${ADMIN_API_KEY}
```

키는 URL, 로그 또는 대시보드의 `localStorage`에 저장하지 않습니다. 대시보드는 `sessionStorage`만 사용합니다.

| 코드 | 의미 |
| --- | --- |
| `400` | 잘못된 필터 또는 사용할 수 없는 출처 |
| `401` | 관리자 인증 헤더 누락 |
| `403` | 관리자 키 불일치 |
| `404` | 공고·프로필·수집 실행 기록 없음 |
| `422` | 요청 또는 쿼리 검증 실패 |
| `503` | DB 등 필수 내부 의존성 사용 불가 |

### 상태 확인

| Method | Path | 설명 |
| --- | --- | --- |
| `GET` | `/health` | 프로세스 생존 확인 |
| `GET` | `/ready` | DB 연결 및 프로필 로드 확인 |

```sh
curl http://localhost:8000/ready
```

### 공고 조회

| Method | Path | 설명 |
| --- | --- | --- |
| `GET` | `/api/v1/jobs` | 공고 목록·필터·커서 페이지네이션 |
| `GET` | `/api/v1/jobs/{job_id}` | 공고 상세 |
| `GET` | `/api/v1/jobs/{job_id}/snapshots` | 저장된 스냅샷 |
| `GET` | `/api/v1/jobs/{job_id}/changes` | 변경 이력 |

목록 필터: `keyword`, `profile_id`, `sources`, `statuses`, `categories`, `skills`, `region`, `employment_types`, `experience_types`, `min_experience`, `max_experience`, `limit`(1–100), `cursor`, `sort`를 지원합니다. 정렬 기준은 `deadline_date`, `company_name`, `title`, `source`, `region`, `experience`, `employment_type`, `updated_at`, `first_seen_at`이며 각각 `:asc` 또는 `:desc`를 붙입니다. `profile_id`를 지정하면 해당 프로필로 새로 매핑된 공고만 반환합니다. 기존 공고는 소급 매핑하지 않습니다. `experience_types`는 `NEWBIE`, `EXPERIENCED`, `ANY`, `UNKNOWN` 값을 사용합니다. 프로필의 `company_queries`는 출처별 회사명·영문명·약칭 검색어이며 WANTED·사람인·잡코리아 등 해당 출처 동기화에 함께 사용됩니다.

### 사람인 연동

사람인 공식 Open API의 `job-search` 엔드포인트를 사용합니다. 사람인 개발자센터에서 발급받은 인증키를 `.env`의 `SARAMIN_ACCESS_KEY`에 넣고 `SARAMIN_ENABLED=true`로 설정하면 동기화 대상에 포함됩니다. `SARAMIN_BASE_URL`은 기본값(`https://oapi.saramin.co.kr`)을 그대로 사용하면 됩니다. 검색 응답에 포함된 공고 정보(제목·회사·지역·고용형태·경력·게시/마감일·키워드)만 저장하며, 공식 검색 API가 제공하지 않는 상세 본문은 비워 둡니다.

사람인 인증키 없이 사용하려면 `SARAMIN_PUBLIC_ENABLED=true`를 설정합니다. 이 경우 사람인 공개 검색·상세 페이지를 직접 조회하며 `SARAMIN_PUBLIC_REQUEST_DELAY_SECONDS`로 요청 간격을 조절합니다. `SARAMIN_ENABLED=true`와 유효한 API 키가 함께 설정되면 공식 API 방식이 우선됩니다.

모든 출처의 기본 요청 간격에 무작위 지연을 추가하려면 `REQUEST_RANDOM_DELAY_ENABLED=true`와 `REQUEST_RANDOM_DELAY_MAX_SECONDS`(기본 0.5초)를 설정합니다. 대시보드 설정에서도 변경할 수 있으며 저장 즉시 실행 중인 어댑터에 반영됩니다.

외부에서 운영 중인 Tor를 선택적으로 사용하려면 `TOR_ENABLED=true`로 설정하고 `TOR_SOCKS_PROXY_URL=socks5://tor:9050`을 사용합니다. ControlPort 수동 회선 변경은 `TOR_CONTROL_ENABLED=true`, `TOR_CONTROL_HOST`, `TOR_CONTROL_PORT`, `TOR_CONTROL_PASSWORD`(해시가 아닌 원문 비밀번호)를 설정한 뒤 대시보드의 **새 Tor 회선 요청** 버튼 또는 `POST /api/v1/admin/tor/newnym`을 사용합니다. Tor의 `TOR_HASHED_CONTROL_PASSWORD`는 Tor 컨테이너에서만 관리하며 이 프로젝트에는 넣지 않습니다. 429/403 발생 시 자동 회선 변경·동일 요청 재전송은 하지 않고 실패 처리합니다.

잡코리아는 `JOBKOREA_ENABLED=true`로 공개 검색/상세 페이지 수집을 활성화할 수 있습니다. 공개 HTML과 JSON-LD에 노출된 정보만 사용하며, 요청 간격은 `JOBKOREA_REQUEST_DELAY_SECONDS`로 조정합니다. 사이트 정책 변경이나 접근 제한 시 해당 공고만 실패 처리될 수 있습니다.

삼성·LG·현대 공식 채용 사이트도 공개 페이지 어댑터로 지원합니다. 각각 `SAMSUNG_ENABLED`, `LG_ENABLED`, `HYUNDAI_ENABLED`를 `true`로 설정하면 활성화됩니다. 상세 페이지 구조 변경이나 접근 제한은 개별 실패로 기록하며, 로그인·캡차·비공개 API 우회는 수행하지 않습니다.

검색 동기화는 각 출처의 페이지네이션을 따라가며 빈 페이지 또는 마지막 페이지까지 수집합니다. 페이지 수를 제공하지 않는 공개 페이지는 중복·빈 결과로 종료하고, 오작동하는 페이지 링크로 인한 무한 요청을 막기 위해 검색어당 최대 100페이지를 안전 상한으로 둡니다.

```sh
curl -G http://localhost:8000/api/v1/jobs \
  --data-urlencode 'statuses=ACTIVE' \
  --data-urlencode 'categories=CPP,EMBEDDED' \
  --data-urlencode 'limit=20'
```

응답 예시:

```json
{
  "items": [{
    "id": "uuid",
    "source": "WANTED",
    "source_job_id": "373576",
    "company_name": "스누아이랩",
    "title": "C#/C++ 개발자",
    "effective_status": "ACTIVE",
    "categories": ["CPP"],
    "skills": [],
    "url": "https://www.wanted.co.kr/wd/373576"
  }],
  "page": {"limit": 20, "next_cursor": null}
}
```

`ACTIVE`는 출처의 명시적 활성 상태 또는 유효한 지원 동작으로 확인된 경우만 사용합니다. 명시적 마감은 `CLOSED`, 삭제/404는 `DELETED`, 확정할 수 없는 경우는 `UNKNOWN`입니다.

### 출처·프로필·대시보드

| Method | Path | 설명 |
| --- | --- | --- |
| `GET` | `/api/v1/sources` | 출처 활성 상태와 지원 기능 |
| `GET` | `/api/v1/profiles` | YAML 검색 프로필 목록 |
| `GET` | `/api/v1/profiles/{profile_id}` | 프로필 상세 |
| `GET` | `/api/v1/dashboard/summary` | 공고·출처·최근 수집 요약 |

### 관리자 수집 API

| Method | Path | 설명 |
| --- | --- | --- |
| `POST` | `/api/v1/admin/sync` | 활성화된 모든 출처 동기화 |
| `POST` | `/api/v1/admin/sync/cancel` | 실행 중인 동기화 중지 요청 |
| `POST` | `/api/v1/admin/sources/{source}/sync` | 특정 출처 동기화 |
| `POST` | `/api/v1/admin/sources/{source}/recheck` | 출처 공고 재확인 실행 |
| `POST` | `/api/v1/admin/jobs/{job_id}/recheck` | 특정 공고 재확인 실행 |
| `POST` | `/api/v1/admin/profiles/reload` | YAML 프로필 다시 로드 |
| `GET` | `/api/v1/admin/crawl-runs` | 최근 수집 실행 목록 |
| `GET` | `/api/v1/admin/crawl-runs/{run_id}` | 수집 실행 상세 |
| `DELETE` | `/api/v1/admin/jobs` | 공고·변경 이력 전체 삭제 (확인 문자열 필요) |

동기화 본문은 선택적 프로필과 모드를 받습니다. 현재 지원 모드는 `incremental`입니다. `profile`을 생략하면 등록된 모든 프로필의 검색어를 출처별로 합쳐 순차 실행합니다.

```sh
curl -X POST http://localhost:8000/api/v1/admin/sync \
  -H "Authorization: Bearer $ADMIN_API_KEY" \
  -H 'Content-Type: application/json' \
  -d '{"profile":"mobility_sdv_security_cpp","mode":"incremental"}'
```

요청이 등록되면 백그라운드 실행 상태를 반환합니다.

```json
{"status":"QUEUED","message":"동기화가 백그라운드에서 시작됩니다.","profiles":["mobility_sdv_security_cpp"]}
```

전체 삭제는 다음 본문이 정확히 일치할 때만 실행됩니다. 수집 실행 이력과 프로필은 삭제하지 않습니다.

```json
{"confirm":"DELETE_ALL"}
```

수집 과정에서 출처 하나 또는 일부 공고가 실패해도 성공한 결과는 저장되며 실행 상태는 `PARTIAL_SUCCESS`가 됩니다. 관리자 중지 요청으로 현재 요청 이후 동기화를 멈추면 `CANCELLED`로 기록합니다. 검색 목록에서 사라진 사실만으로 공고를 마감 처리하지 않습니다.

### 수집 일정

대시보드 **설정**에서 Cron 형식(분 시 일 월 요일)으로 검색 동기화와 재확인 일정을 변경할 수 있습니다. 예약 동기화는 등록된 모든 프로필의 출처별 검색어를 합쳐 출처마다 순차 실행하며, 중복 공고는 한 번만 처리합니다. 수집 진행 상황은 기본 10건 단위(`SYNC_COMMIT_BATCH_SIZE`)로 DB에 커밋되며 대시보드에서 실행 중 카운터를 확인할 수 있습니다. 설정은 PostgreSQL에 저장되며 Scheduler 컨테이너가 최대 30초 안에 반영합니다.

| Method | Path | 설명 |
| --- | --- | --- |
| `GET` | `/api/v1/admin/settings/schedule` | 현재 수집 일정 조회 |
| `PUT` | `/api/v1/admin/settings/schedule` | 수집 일정 변경 |
| `GET` | `/api/v1/admin/settings/request-pacing` | 요청 랜덤 지연 설정 조회 |
| `PUT` | `/api/v1/admin/settings/request-pacing` | 요청 랜덤 지연 설정 변경(즉시 적용) |
| `POST` | `/api/v1/admin/tor/newnym` | 외부 Tor ControlPort에 수동 새 회선 요청 |

```json
{"sync_cron":"0 2 * * *","recheck_cron":"0 3 * * *"}
```

요청 지연 설정 예시:

```json
{
  "random_delay_enabled": true,
  "random_delay_max_seconds": 0.5
}
```

Tor 회선 변경은 `TOR_CONTROL_ENABLED=true`인 경우에만 동작하며, `TOR_CONTROL_PASSWORD`는 Tor의 해시가 아닌 원문 비밀번호입니다. 429/403 발생 시 자동 회선 변경이나 동일 요청 재전송은 수행하지 않습니다.

완료된 출처 검색에서 기존 `ACTIVE` 공고가 보이지 않으면 마감으로 단정하지 않고 `UNKNOWN`으로 전환하며 변경 이력을 남깁니다. 이후 출처가 명시적 마감·삭제·활성 상태를 제공할 때 각각 `CLOSED`·`DELETED`·`ACTIVE`로 갱신됩니다.

### 프로필 관리

기본 YAML 프로필은 최초 시작 시 DB에 시드됩니다. 이후 대시보드의 **프로필** 화면에서 관리자 키를 입력한 세션으로 프로필을 추가·수정·삭제할 수 있으며, 변경 내용은 PostgreSQL에 영속화됩니다.

| Method | Path | 설명 |
| --- | --- | --- |
| `POST` | `/api/v1/admin/profiles` | 프로필 생성 |
| `PUT` | `/api/v1/admin/profiles/{profile_id}` | 프로필 수정 (ID 변경 불가) |
| `DELETE` | `/api/v1/admin/profiles/{profile_id}` | 프로필 삭제 |

```json
{
  "id": "automotive_security",
  "display_name": "차량 보안 개발자",
  "queries": ["차량 보안 C++ 개발자"],
  "include_keywords": ["PKI", "HSM", "C++"],
  "exclude_keywords": ["영업"],
  "source_queries": {"WANTED": ["Automotive Security C++"]}
}
```

원티드 어댑터는 공개 페이지의 정상 HTTP 응답만 사용하며 CAPTCHA·프록시·접근 제한 우회를 수행하지 않습니다. 운영 전 출처의 이용약관 및 robots 정책을 확인하세요.

관리자 동기화 API는 수집 시간이 긴 출처를 고려해 `202 QUEUED`를 즉시 반환하고 백그라운드에서 실행합니다. 결과는 관리자 크롤 실행 목록 API에서 확인합니다.
