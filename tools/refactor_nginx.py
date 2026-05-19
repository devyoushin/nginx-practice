#!/usr/bin/env python3
"""
nginx.conf 리팩토링 도구

모놀리식 nginx.conf를 분석하여:
1. server 블록별로 conf.d/ 파일 분리
2. 중복 proxy_pass URL을 upstream 블록으로 추출 (같은 host:port는 하나로)
3. 반복되는 proxy 헤더를 snippet으로 분리
4. 정리된 메인 nginx.conf 생성

사용법:
    python3 refactor_nginx.py /path/to/nginx.conf
    python3 refactor_nginx.py /path/to/nginx.conf --output-dir ./output
    python3 refactor_nginx.py /path/to/nginx.conf --dry-run
"""

import re
import sys
import os
import argparse
from collections import Counter, defaultdict
from dataclasses import dataclass, field


# ─────────────────────────────────────────────
# 1. 파싱
# ─────────────────────────────────────────────

@dataclass
class Block:
    """nginx config의 블록 하나를 표현"""
    directive: str          # e.g. "server", "location /api", "upstream backend"
    content: str            # 블록 내부 원문 (중괄호 제외)
    raw: str                # 블록 전체 원문 (중괄호 포함)
    line_start: int = 0
    children: list = field(default_factory=list)


def find_matching_brace(text: str, start: int) -> int:
    """start 위치의 '{' 에 대응하는 '}' 위치를 반환"""
    depth = 0
    i = start
    in_quote = False
    quote_char = None
    while i < len(text):
        ch = text[i]
        if in_quote:
            if ch == quote_char and (i == 0 or text[i-1] != '\\'):
                in_quote = False
        else:
            if ch in ('"', "'"):
                in_quote = True
                quote_char = ch
            elif ch == '{':
                depth += 1
            elif ch == '}':
                depth -= 1
                if depth == 0:
                    return i
        i += 1
    return -1


def extract_blocks(text: str, block_type: str) -> list[Block]:
    """특정 타입의 최상위 블록들을 추출"""
    if block_type == 'location':
        pattern = re.compile(r'^([ \t]*location\s+[^{]+)\{', re.MULTILINE)
    elif block_type == 'upstream':
        pattern = re.compile(r'^([ \t]*upstream\s+\S+\s*)\{', re.MULTILINE)
    else:
        pattern = re.compile(rf'^([ \t]*{block_type}\s*)\{{', re.MULTILINE)

    blocks = []
    for m in pattern.finditer(text):
        brace_start = m.end() - 1
        brace_end = find_matching_brace(text, brace_start)
        if brace_end == -1:
            continue
        directive = m.group(1).strip()
        content = text[brace_start + 1:brace_end]
        raw = text[m.start():brace_end + 1]
        line_start = text[:m.start()].count('\n') + 1
        blocks.append(Block(directive=directive, content=content, raw=raw, line_start=line_start))
    return blocks


def parse_nginx_conf(text: str) -> dict:
    """nginx.conf 전체를 파싱하여 구조화된 dict 반환"""
    result = {
        'main_context': '',
        'events_block': None,
        'http_block': None,
        'stream_blocks': [],
        'server_blocks': [],
        'upstream_blocks': [],
        'existing_upstreams': set(),
    }

    events = extract_blocks(text, 'events')
    if events:
        result['events_block'] = events[0]

    result['stream_blocks'] = extract_blocks(text, 'stream')

    http_blocks = extract_blocks(text, 'http')
    if http_blocks:
        http_block = http_blocks[0]
        result['http_block'] = http_block
        result['upstream_blocks'] = extract_blocks(http_block.content, 'upstream')
        for ub in result['upstream_blocks']:
            name = ub.directive.replace('upstream', '').strip()
            result['existing_upstreams'].add(name)
        result['server_blocks'] = extract_blocks(http_block.content, 'server')
        for sb in result['server_blocks']:
            sb.children = extract_blocks(sb.content, 'location')

    main = text
    for block in events + http_blocks + result['stream_blocks']:
        main = main.replace(block.raw, '')
    result['main_context'] = main.strip()

    return result


# ─────────────────────────────────────────────
# 2. 분석
# ─────────────────────────────────────────────

@dataclass
class UpstreamInfo:
    name: str               # upstream 이름
    host_port: str           # e.g. "10.0.1.10:8080"
    scheme: str              # "http" or "https"
    urls: list = field(default_factory=list)  # 이 upstream을 참조하는 원본 URL 목록


@dataclass
class AnalysisResult:
    proxy_pass_urls: Counter
    proxy_header_groups: list
    server_names: list
    upstreams: dict[str, UpstreamInfo]   # host_port -> UpstreamInfo
    url_to_upstream: dict[str, tuple]    # url -> (upstream_name, path)


def analyze(parsed: dict) -> AnalysisResult:
    """파싱된 결과를 분석하여 리팩토링 대상 식별"""
    proxy_pass_pattern = re.compile(r'proxy_pass\s+(https?://[^;]+);', re.IGNORECASE)

    # proxy_pass URL 수집
    proxy_pass_urls = Counter()
    for sb in parsed['server_blocks']:
        for m in proxy_pass_pattern.finditer(sb.content):
            proxy_pass_urls[m.group(1).strip()] += 1

    # proxy 헤더 그룹 수집
    proxy_header_pattern = re.compile(r'(proxy_set_header\s+\S+\s+[^;]+;)', re.IGNORECASE)
    header_groups = []
    for sb in parsed['server_blocks']:
        for loc in sb.children:
            headers = proxy_header_pattern.findall(loc.content)
            if len(headers) >= 2:
                header_groups.append(tuple(h.strip() for h in headers))

    header_counter = Counter(header_groups)
    common_headers = [g for g, c in header_counter.most_common(5) if c >= 2]

    # server_name 수집
    sn_pattern = re.compile(r'server_name\s+([^;]+);')
    server_names = []
    for sb in parsed['server_blocks']:
        m = sn_pattern.search(sb.content)
        server_names.append(m.group(1).strip() if m else '_')

    # upstream 생성: 같은 host:port는 하나의 upstream으로 합침
    upstreams: dict[str, UpstreamInfo] = {}
    url_to_upstream: dict[str, tuple] = {}
    used_names = set(parsed['existing_upstreams'])

    for url in proxy_pass_urls:
        match = re.match(r'(https?)://([^/]+)(.*)', url)
        if not match:
            continue
        scheme = match.group(1)
        host_port = match.group(2)
        path = match.group(3) or ''

        if host_port not in upstreams:
            name = _host_to_upstream_name(host_port, used_names)
            upstreams[host_port] = UpstreamInfo(
                name=name, host_port=host_port, scheme=scheme, urls=[url]
            )
        else:
            upstreams[host_port].urls.append(url)

        info = upstreams[host_port]
        url_to_upstream[url] = (info.name, path, info.scheme)

    return AnalysisResult(
        proxy_pass_urls=proxy_pass_urls,
        proxy_header_groups=common_headers,
        server_names=server_names,
        upstreams=upstreams,
        url_to_upstream=url_to_upstream,
    )


def _host_to_upstream_name(host_port: str, used: set) -> str:
    """host:port로부터 의미 있는 upstream 이름 생성"""
    # IP 기반이면 ip_port 형태, 도메인이면 도메인 기반
    host, _, port = host_port.partition(':')

    if re.match(r'^\d+\.\d+\.\d+\.\d+$', host):
        # IP: 마지막 옥텟 + 포트
        last_octet = host.split('.')[-1]
        name = f"backend_{last_octet}"
        if port and port not in ('80', '443'):
            name += f"_{port}"
    else:
        # 도메인: 서브도메인 기반
        parts = host.split('.')
        name = parts[0] if parts[0] not in ('www', 'api') else '_'.join(parts[:2])
        name = re.sub(r'[^a-zA-Z0-9]', '_', name)

    name = re.sub(r'_+', '_', name).strip('_')
    if not name:
        name = 'backend'

    base = name
    counter = 1
    while name in used:
        name = f"{base}_{counter}"
        counter += 1
    used.add(name)
    return name


# ─────────────────────────────────────────────
# 3. 리팩토링 출력
# ─────────────────────────────────────────────

class NginxRefactorer:
    def __init__(self, parsed: dict, analysis: AnalysisResult, output_dir: str):
        self.parsed = parsed
        self.analysis = analysis
        self.output_dir = output_dir
        self.files_to_write: dict[str, str] = {}

    def refactor(self):
        self._generate_proxy_snippets()
        self._generate_upstream_conf()
        self._generate_server_confs()
        self._generate_main_conf()
        return self.files_to_write

    def _generate_proxy_snippets(self):
        path = os.path.join(self.output_dir, 'snippets', 'proxy_params.conf')
        if self.analysis.proxy_header_groups:
            main_group = self.analysis.proxy_header_groups[0]
            lines = [
                "# 공통 proxy 헤더 설정",
                "# 사용: include snippets/proxy_params.conf;",
                "",
            ]
            for header in main_group:
                lines.append(header)
            self.files_to_write[path] = '\n'.join(lines) + '\n'
        else:
            self.files_to_write[path] = (
                "# 공통 proxy 헤더 설정\n"
                "# 사용: include snippets/proxy_params.conf;\n\n"
                "proxy_set_header Host $host;\n"
                "proxy_set_header X-Real-IP $remote_addr;\n"
                "proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;\n"
                "proxy_set_header X-Forwarded-Proto $scheme;\n"
                "proxy_http_version 1.1;\n"
                "proxy_connect_timeout 60s;\n"
                "proxy_send_timeout 60s;\n"
                "proxy_read_timeout 60s;\n"
            )

        # WebSocket snippet
        ws_path = os.path.join(self.output_dir, 'snippets', 'websocket.conf')
        self.files_to_write[ws_path] = (
            "# WebSocket proxy 설정\n"
            "# 사용: include snippets/websocket.conf;\n\n"
            "proxy_http_version 1.1;\n"
            "proxy_set_header Upgrade $http_upgrade;\n"
            'proxy_set_header Connection "upgrade";\n'
            "proxy_set_header Host $host;\n"
            "proxy_read_timeout 86400s;\n"
        )

    def _generate_upstream_conf(self):
        if not self.analysis.upstreams:
            return

        lines = ["# upstream 정의", "# 같은 host:port는 하나의 upstream으로 관리", ""]

        for host_port, info in self.analysis.upstreams.items():
            lines.append(f"# {info.scheme}://{host_port}")
            lines.append(f"upstream {info.name} {{")
            lines.append(f"    server {host_port};")
            lines.append(f"    keepalive 32;")
            lines.append(f"}}")
            lines.append("")

        self.files_to_write[
            os.path.join(self.output_dir, 'upstream.d', 'backends.conf')
        ] = '\n'.join(lines)

    def _generate_server_confs(self):
        sn_pattern = re.compile(r'server_name\s+([^;]+);')
        listen_pattern = re.compile(r'listen\s+([^;]+);')
        filenames_used = Counter()

        for i, sb in enumerate(self.parsed['server_blocks']):
            # 파일 이름 결정
            m = sn_pattern.search(sb.content)
            server_name = m.group(1).strip().split()[0] if m else f'server_{i}'

            lm = listen_pattern.search(sb.content)
            listen_port = ''
            if lm:
                port_match = re.search(r'(\d+)', lm.group(1))
                if port_match:
                    listen_port = port_match.group(1)

            safe_name = re.sub(r'[^a-zA-Z0-9._-]', '_', server_name)
            if listen_port and listen_port not in ('80', '443'):
                filename = f"{safe_name}_{listen_port}.conf"
            elif listen_port == '443' or 'ssl' in sb.content:
                filename = f"{safe_name}_ssl.conf"
            else:
                filename = f"{safe_name}.conf"

            # 파일명 중복 처리
            filenames_used[filename] += 1
            if filenames_used[filename] > 1:
                base, ext = os.path.splitext(filename)
                filename = f"{base}_{filenames_used[filename]}{ext}"

            content = self._refactor_server_block(sb)
            self.files_to_write[
                os.path.join(self.output_dir, 'conf.d', filename)
            ] = content

    def _refactor_server_block(self, sb: Block) -> str:
        content = sb.content

        # 1) proxy_pass URL → upstream 치환
        for url, (upstream_name, path, scheme) in self.analysis.url_to_upstream.items():
            replacement = f"{scheme}://{upstream_name}{path}"
            content = content.replace(f'proxy_pass {url}', f'proxy_pass {replacement}')

        # 2) 반복 proxy 헤더 → include 치환
        if self.analysis.proxy_header_groups:
            content = self._replace_headers_with_include(
                content, self.analysis.proxy_header_groups[0]
            )

        # 들여쓰기 정리
        content = self._clean_content(content)
        return f"server {{\n{content}}}\n"

    def _replace_headers_with_include(self, content: str, header_group: tuple) -> str:
        locations = extract_blocks(f"wrapper {{\n{content}\n}}", 'location')

        for loc in locations:
            if not all(h in loc.content for h in header_group):
                continue

            new_content = loc.content
            for header in header_group:
                # 헤더 라인 전체를 제거 (앞 공백 포함)
                new_content = re.sub(
                    r'^[ \t]*' + re.escape(header) + r'[ \t]*\n',
                    '', new_content, flags=re.MULTILINE
                )

            # 빈 줄 정리 후 include 삽입
            new_content = re.sub(r'\n{3,}', '\n\n', new_content)

            # proxy_pass 앞에 include 삽입
            proxy_match = re.search(r'^([ \t]*)(proxy_pass\s)', new_content, re.MULTILINE)
            if proxy_match:
                indent = proxy_match.group(1)
                pos = proxy_match.start()
                include_line = f"{indent}include snippets/proxy_params.conf;\n"
                new_content = new_content[:pos] + include_line + new_content[pos:]

            content = content.replace(loc.content, new_content)

        return content

    def _clean_content(self, text: str) -> str:
        """들여쓰기 정리 및 빈 줄 축소"""
        lines = text.split('\n')
        result = []
        prev_empty = False

        for line in lines:
            stripped = line.strip()

            # 연속 빈 줄 방지
            if not stripped:
                if not prev_empty and result:
                    result.append('')
                prev_empty = True
                continue
            prev_empty = False

            # 최소 4칸 들여쓰기 보장
            leading = len(line) - len(line.lstrip())
            if leading < 4:
                result.append(f'    {stripped}')
            else:
                result.append(line)

        # 앞뒤 빈 줄 정리
        while result and result[0] == '':
            result.pop(0)
        while result and result[-1] == '':
            result.pop()

        return '\n'.join(result) + '\n'

    def _generate_main_conf(self):
        parts = []

        # main context
        if self.parsed['main_context']:
            parts.append(self.parsed['main_context'])
        else:
            parts.append(
                "user nginx;\n"
                "worker_processes auto;\n"
                "error_log /var/log/nginx/error.log warn;\n"
                "pid /run/nginx.pid;"
            )
        parts.append('')

        # events
        if self.parsed['events_block']:
            parts.append(self.parsed['events_block'].raw)
        else:
            parts.append(
                "events {\n"
                "    worker_connections 1024;\n"
                "    multi_accept on;\n"
                "    use epoll;\n"
                "}"
            )
        parts.append('')

        # http
        parts.append('http {')
        parts.append('    include       mime.types;')
        parts.append('    default_type  application/octet-stream;')
        parts.append('')

        # http 공통 설정 추출
        http_settings = self._extract_http_settings()
        if http_settings:
            parts.append(http_settings)
            parts.append('')

        parts.append('    # Upstream 정의')
        parts.append('    include upstream.d/*.conf;')
        parts.append('')
        parts.append('    # 가상 호스트 (server 블록)')
        parts.append('    include conf.d/*.conf;')
        parts.append('}')

        for stream in self.parsed['stream_blocks']:
            parts.append('')
            parts.append(stream.raw)

        self.files_to_write[
            os.path.join(self.output_dir, 'nginx.conf')
        ] = '\n'.join(parts) + '\n'

    def _extract_http_settings(self) -> str:
        if not self.parsed['http_block']:
            return ''

        content = self.parsed['http_block'].content

        # server, upstream 블록 제거
        for sb in self.parsed['server_blocks']:
            content = content.replace(sb.raw, '')
        for ub in self.parsed['upstream_blocks']:
            content = content.replace(ub.raw, '')

        # 이미 메인에 넣은 것 제거
        content = re.sub(r'^\s*include\s+mime\.types;\s*$', '', content, flags=re.MULTILINE)
        content = re.sub(r'^\s*default_type\s+[^;]+;\s*$', '', content, flags=re.MULTILINE)

        # 주석만 있는 줄 제거 (섹션 구분용 주석 잔해)
        content = re.sub(r'^\s*#\s*─+.*$', '', content, flags=re.MULTILINE)
        content = re.sub(r'^\s*#\s*$', '', content, flags=re.MULTILINE)
        # server 블록 제거 후 남은 고아 주석 제거 (앞뒤에 지시어가 없는 주석)
        content = re.sub(r'^\s*#\s*[^#\n]+\s*$(?=\s*$)', '', content, flags=re.MULTILINE)

        # 빈 줄 정리
        content = re.sub(r'\n{3,}', '\n\n', content).strip()

        if not content:
            return ''

        lines = []
        for line in content.split('\n'):
            s = line.strip()
            if s:
                # 주석으로만 이루어진 섹션 구분선 건너뛰기
                if re.match(r'^#\s*[-─=]+\s*$', s):
                    continue
                lines.append(f'    {s}')
            else:
                lines.append('')
        return '\n'.join(lines)


# ─────────────────────────────────────────────
# 4. 리포트
# ─────────────────────────────────────────────

def print_report(parsed: dict, analysis: AnalysisResult):
    print("=" * 60)
    print("  nginx.conf 분석 리포트")
    print("=" * 60)
    print()

    print("[구조]")
    print(f"  - server 블록: {len(parsed['server_blocks'])}개")
    total_locations = sum(len(sb.children) for sb in parsed['server_blocks'])
    print(f"  - location 블록: {total_locations}개")
    print(f"  - 기존 upstream 블록: {len(parsed['upstream_blocks'])}개")
    print()

    print("[server 블록 목록]")
    for i, name in enumerate(analysis.server_names):
        loc_count = len(parsed['server_blocks'][i].children)
        print(f"  {i+1}. {name} ({loc_count} locations)")
    print()

    print("[proxy_pass URL 분석]")
    if analysis.proxy_pass_urls:
        # 같은 host:port 그룹으로 표시
        by_host = defaultdict(list)
        for url in analysis.proxy_pass_urls:
            m = re.match(r'https?://([^/]+)(.*)', url)
            if m:
                by_host[m.group(1)].append(url)
        for host_port, urls in by_host.items():
            total = sum(analysis.proxy_pass_urls[u] for u in urls)
            upstream_name = analysis.upstreams.get(host_port, None)
            name = upstream_name.name if upstream_name else '?'
            print(f"  {host_port} → upstream {name} (URL {len(urls)}개, 총 {total}회)")
            for url in urls:
                print(f"    - {url}")
    else:
        print("  proxy_pass 없음")
    print()

    print("[리팩토링 항목]")
    suggestions = []
    if len(parsed['server_blocks']) > 1:
        suggestions.append(f"server 블록 {len(parsed['server_blocks'])}개 → conf.d/ 분리")
    if analysis.upstreams:
        suggestions.append(f"백엔드 {len(analysis.upstreams)}개 → upstream.d/ 추출")
    dup = sum(1 for c in analysis.proxy_pass_urls.values() if c >= 2)
    if dup:
        suggestions.append(f"중복 proxy_pass URL {dup}개 → upstream 참조로 치환")
    if analysis.proxy_header_groups:
        suggestions.append(f"반복 proxy 헤더 {len(analysis.proxy_header_groups)}그룹 → snippet 분리")
    for i, s in enumerate(suggestions, 1):
        print(f"  {i}. {s}")
    print()


# ─────────────────────────────────────────────
# 5. 메인
# ─────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description='nginx.conf 리팩토링 도구',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
예시:
  # 분석만 (변경 없음)
  python3 refactor_nginx.py nginx.conf --dry-run

  # 리팩토링 결과를 ./output 에 생성
  python3 refactor_nginx.py nginx.conf --output-dir ./output

  # 기본 출력 디렉토리 (./refactored/)
  python3 refactor_nginx.py nginx.conf
        """
    )
    parser.add_argument('config', help='원본 nginx.conf 파일 경로')
    parser.add_argument('--output-dir', '-o', default='./refactored',
                        help='출력 디렉토리 (기본: ./refactored)')
    parser.add_argument('--dry-run', '-n', action='store_true',
                        help='분석 리포트만 출력하고 파일 생성 안 함')

    args = parser.parse_args()

    if not os.path.isfile(args.config):
        print(f"Error: 파일을 찾을 수 없습니다: {args.config}", file=sys.stderr)
        sys.exit(1)

    with open(args.config, 'r', encoding='utf-8') as f:
        raw_text = f.read()

    print(f"원본 파일: {args.config} ({len(raw_text.splitlines())}줄)")
    print()

    parsed = parse_nginx_conf(raw_text)
    analysis = analyze(parsed)
    print_report(parsed, analysis)

    if args.dry_run:
        print("(--dry-run 모드: 파일 생성을 건너뜁니다)")
        return

    refactorer = NginxRefactorer(parsed, analysis, args.output_dir)
    files = refactorer.refactor()

    for filepath, content in sorted(files.items()):
        os.makedirs(os.path.dirname(filepath), exist_ok=True)
        with open(filepath, 'w', encoding='utf-8') as f:
            f.write(content)
        rel = os.path.relpath(filepath)
        lines = content.count('\n')
        print(f"  생성: {rel} ({lines}줄)")

    print()
    print(f"총 {len(files)}개 파일이 '{args.output_dir}/'에 생성되었습니다.")
    print()
    print("다음 단계:")
    print(f"  1. 결과 확인:   ls -la {args.output_dir}/")
    print(f"  2. 설정 검증:   nginx -t -c $(pwd)/{args.output_dir}/nginx.conf")
    print(f"  3. 백업 후 적용: cp -r {args.output_dir}/* /etc/nginx/")


if __name__ == '__main__':
    main()
