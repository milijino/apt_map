# 수도권 내집 예산지도

매매가 상한을 천만 원 단위로 정하면 서울·경기에서 그 이하 실거래 아파트를 지도에 띄우고,
대출 조건(소득·금리·만기·생애최초)과 보유 현금을 넣으면 단지별로 **실제 필요한 현금**을 계산해 줍니다.

- 가격: 국토교통부 아파트 매매 실거래가, 최근 6개월, 단지·전용면적별 최근 3건 중앙값 (해제 거래 제외)
- 대출: 일반 주담대 기준 LTV·주택가격별 한도·스트레스 DSR 중 가장 낮은 값
- 필요 현금 = 매매가 + 취득세·교육세·농특세 + 중개보수(상한) + 기타 비용 − 대출
- 데이터는 매월 3일 새벽 GitHub Actions가 자동으로 갱신

## 파일 구성

| 파일 | 역할 |
| --- | --- |
| `index.html` | 앱 화면 (지도: Leaflet + OpenStreetMap, 키 필요 없음) |
| `data/rules.json` | 대출·규제지역 규칙. **정책이 바뀌면 이 파일만 고치면 됨** |
| `data/apartments.json` | 단지 데이터. 처음엔 샘플, 첫 자동 실행 후 실거래로 교체 |
| `data/geocache.json` | 좌표 캐시 (다음 달부터는 신규 단지만 카카오 호출) |
| `scripts/build_data.py` | 실거래 수집·집계·좌표 변환 |
| `.github/workflows/monthly-update.yml` | 월 1회 자동 실행 |

## 처음 설정 (한 번만)

1. **공공데이터포털 키**: data.go.kr 에서 "국토교통부_아파트 매매 실거래가 자료" 활용신청 → 마이페이지의 **일반 인증키(Decoding)** 복사
2. **카카오 REST 키**: developers.kakao.com → 기존 앱(토토 지도용) → 앱 키의 **REST API 키** 복사. 제품 설정에서 **카카오맵** 사용 설정이 켜져 있어야 주소 검색이 됩니다
3. GitHub에 새 저장소 `apt_map` 만들고 이 폴더 전체 업로드
4. 저장소 Settings → Secrets and variables → Actions → New repository secret
   - `DATA_GO_KR_KEY` = 1번 키
   - `KAKAO_REST_KEY` = 2번 키
5. Settings → Pages → Branch `main` / `(root)` 저장 → `https://milijino.github.io/apt_map/`
6. Actions 탭 → "월간 실거래 업데이트" → **Run workflow** 로 첫 수집 실행 (첫 회는 좌표 변환 때문에 30~60분)

## 규칙 수정 예시 (`data/rules.json`)

- 규제지역 추가·해제: `regulatedAreas` 에 지역 이름 추가/삭제 (예: `"경기 화성시 동탄구"`)
- LTV 변경: `ltv.regulated` 등
- 주택가격별 한도: `loanCapByPrice`
- 스트레스 금리: `stressRate`, 금리유형별 반영 비율 `stressShare`

## 참고

- 결과는 추정치입니다. 은행은 KB시세·감정가로 한도를 잡고, 소득 인정 방식·우대 조건에 따라 실제 한도가 달라집니다.
- 실행 로그에 "거래 0건 코드"가 나오면 분구로 바뀐 옛 코드(부천 41190, 화성 41590)는 정상입니다. 다른 지역이 0건이면 코드를 확인하세요.
