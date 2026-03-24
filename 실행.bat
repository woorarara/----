@echo off
:: 터미널에서 한글이 깨지지 않도록 UTF-8 인코딩 설정
chcp 65001 > nul

echo ===================================================
echo  *** 온라인 AI 전당포 - 꿀매물 탐지기 서버 구동 중...
echo ===================================================
echo.
echo  잠시만 기다려주세요. 인터넷 창이 자동으로 열립니다!
echo.

:: 이 배치 파일이 있는 현재 폴더로 경로를 자동 이동 (경로 에러 완벽 차단!)
cd /d "%~dp0"

:: 필수 라이브러리가 설치되어 있는지 확인 후 없으면 자동 설치
echo  [1/2] 필수 라이브러리 확인 중...
pip show streamlit >nul 2>&1
if %errorlevel% neq 0 (
    echo  streamlit 이 없습니다. 자동 설치를 시작합니다...
    pip install streamlit requests pandas
    echo.
)

pip show pandas >nul 2>&1
if %errorlevel% neq 0 (
    echo  pandas 가 없습니다. 자동 설치를 시작합니다...
    pip install pandas
    echo.
)

echo  [2/2] Streamlit 앱 실행 중...
echo.
echo  브라우저가 열리면 사이드바에서 검색어를 설정하고
echo  '매물 탐색 시작' 버튼을 눌러주세요!
echo.
echo  종료하려면 이 창을 닫거나 Ctrl+C 를 누르세요.
echo.

:: Streamlit 앱 실행
streamlit run app.py

:: 앱이 종료되거나 에러 발생 시 창이 바로 닫히지 않도록 대기
echo.
echo  서버가 종료되었습니다.
pause
