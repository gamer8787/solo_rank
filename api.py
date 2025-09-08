import datetime
import os
import time

import requests
import json

from env import API_KEY, MAX_RETRIES


def make_request_with_retries(url,headers=None, params=None, max_retries=MAX_RETRIES, delay=10):
    """
    HTTP 요청을 보내고, 실패 시 지정된 횟수만큼 재시도하는 함수.

    Args:
        url (str): 요청할 URL.
        max_retries (int): 최대 재시도 횟수.
        delay (int): 재시도 간격(초).

    Returns:
        dict: 성공적으로 받은 JSON 데이터.

    Raises:
        RuntimeError: 최대 재시도 횟수를 초과한 경우.
    """
    for attempt in range(max_retries):
        response = requests.get(url, params=params, headers=headers)
        if response.status_code == 200:
            return response.json()

        print(f"url is {url}")
        print(f"Attempt {attempt + 1} failed with status code {response.status_code}. Retrying in {delay} seconds...")
        time.sleep(delay)

    raise RuntimeError(f"Failed to complete the request after {max_retries} attempts.")

def get_match_by_gameId(gameId):
    url = f"https://asia.api.riotgames.com/lol/match/v5/matches/{gameId}?api_key={API_KEY}"
    data = make_request_with_retries(url)
    return data

    #침퍼인,룬6개,스탯룬3개 뽑는 함수
def get_champion_and_rune_10_by_puuid(gameId):
    data = get_match_by_gameId(gameId)
    participants_info = []

    for participant in data['info']['participants']:
        champion_name = participant['championName']
        perks = participant['perks']
        primary_runes = [selection['perk'] for selection in perks['styles'][0]['selections']]
        sub_runes = [selection['perk'] for selection in perks['styles'][1]['selections']]
        stat_runes = [perks['statPerks']['offense'], perks['statPerks']['flex'], perks['statPerks']['defense']]

        # Lane 값을 변환
        lane = participant['teamPosition']
        if lane == "TOP":
            lane = "top"
        elif lane == "JUNGLE":
            lane = "jungle"
        elif lane == "MIDDLE":
            lane = "mid"
        elif lane == "BOTTOM":
            lane = "adc"
        elif lane == "UTILITY":
            lane = "support"

        # 챔피언, 룬, 스탯 룬, 및 포지션을 담은 사전 생성
        player_info = {
            "champion": champion_name,
            "primary_runes": primary_runes,
            "sub_runes": sub_runes,
            "stat_runes": stat_runes,
            "lane": lane
        }
        participants_info.append(player_info)

    return participants_info

def get_match_info(gameId, participantId):
    data = get_match_by_gameId(gameId)
    participant = data['info']['participants'][participantId - 1]

    kills = participant['kills']
    deaths = participant['deaths']
    assists = participant['assists']
    lane = participant['teamPosition']
    # Lane 값을 변환
    if lane == "TOP":
        lane = "top"
    elif lane == "JUNGLE":
        lane = "jungle"
    elif lane == "MIDDLE":
        lane = "mid"
    elif lane == "BOTTOM":
        lane = "adc"
    elif lane == "UTILITY":
        lane = "support"
    # Item list from challenges (assuming this is correct)
    itemlist = participant['challenges']['legendaryItemUsed']
    items_in_participant = [
        participant['item0'],
        participant['item1'],
        participant['item2'],
        participant['item3'],
        participant['item4'],
        participant['item5'],
        participant['item6']
    ]
    # itemlist 중에서 participant['item0'] ~ participant['item6']에 있는 값만 필터링하여 중복 제거
    itemlist = list(set([item for item in itemlist if item in items_in_participant]))


    champion_name = participant['championName']
    puuid = participant['puuid']
    # Primary rune: first value from primary_runes
    primary_rune = participant['perks']['styles'][0]['selections'][0]['perk']
    sub_rune = participant['perks']['styles'][1]['style']
    # 첫 번째 보조 룬만 가져오기 (원한다면)
    # sub_rune = sub_runes[0]['perk'] if sub_runes else None

    # Summoner spells IDs
    summoner_ids = [
        participant['summoner1Id'],
        participant['summoner2Id']
    ]

    # Extracting the gameVersion and formatting it to keep only the major and minor version numbers
    game_version_full = data['info']['gameVersion']
    game_version = ".".join(game_version_full.split(".")[:2])

    # Extracting region from platformId
    region = data['info']['platformId']

    tier = get_tier_by_puuid(puuid)
    tier_detail = get_tier_detail_by_puuid(puuid)
    start_time = data['info']['gameStartTimestamp']
    # 새로운 방식으로 상대 챔피언 이름을 가져오기

    opponent_champion_name = None
    for p in data['info']['participants']:
        if p['teamPosition'] == participant['teamPosition'] and p['teamId'] != participant['teamId']:
            opponent_champion_name = p['championName']
            break

    # Constructing the dictionary with the gathered information
    thumbnail_info = {
        "kills": kills,
        "deaths": deaths,
        "assists": assists,
        "itemlist": itemlist,
        "championName": champion_name,
        "puuid": puuid,
        "primaryrune": primary_rune,
        "subrune": sub_rune,
        "summonerIds": summoner_ids,
        "gameVersion": game_version,
        "region": region,
        "tier": tier,
        "tierDetail" : tier_detail,
        "lane": lane,
        "startTime" : start_time,
        "opponentChampionName": opponent_champion_name  # Add the opponent's champion name
    }

    return thumbnail_info
def get_tier_by_puuid(puuid, language='en'):
    # summonerId = get_summonerId_by_puuid(puuid)
    url = f"https://kr.api.riotgames.com/lol/league/v4/entries/by-puuid/{puuid}?api_key={API_KEY}"

    data = make_request_with_retries(url)
    # queueType이 "RANKED_SOLO_5x5"인 항목 찾기
    for entry in data:
        if entry['queueType'] == "RANKED_SOLO_5x5":
            tier = entry['tier']

            if language == 'ko':
                # 티어를 한국어로 변환
                tier_translations = {
                    "CHALLENGER": "챌린저",
                    "GRANDMASTER": "그랜드 마스터",
                    "MASTER": "마스터",
                    "DIAMOND": "다이아몬드",
                    "EMERALD": "에메랄드",
                    "PLATINUM": "플래티넘",
                    "GOLD": "골드",
                    "SILVER": "실버",
                    "BRONZE": "브론즈",
                    "IRON": "아이언"
                }
                tier = tier_translations.get(tier, tier)  # 변환되지 않는 경우 원래 tier 반환

            return f"{tier}"
    # "RANKED_SOLO_5x5"가 없는 경우
    return "Unranked"

def get_kda_time_stamp(game_id, participantId):
    url = f"https://asia.api.riotgames.com/lol/match/v5/matches/{game_id}/timeline?api_key={API_KEY}"
    data = make_request_with_retries(url)
    # 킬 및 어시스트 타임스탬프를 저장할 리스트
    kill_timestamps = []

    # 각 프레임의 이벤트를 확인하여 CHAMPION_KILL 이벤트와 GAME_END 이벤트를 필터링
    for frame in data['info']['frames']:
        for event in frame['events']:
            timestamp = event['timestamp']
            seconds = timestamp // 1000
            position = event.get('position', {})
            x = position.get('x', None)
            y = position.get('y', None)

            if event['type'] == "CHAMPION_KILL":
                # participantId가 죽은 경우 확인
                if event['victimId'] == participantId:
                    kill_timestamps.append((seconds, "death", x, y))

                # 킬러가 participantId인지 확인
                elif event['killerId'] == participantId:
                    # 어시스트가 없는 경우 솔로킬
                    assisting_participants = event.get('assistingParticipantIds', [])
                    if not assisting_participants:
                        kill_type = "solo kill"
                    else:
                        kill_type = "kill"
                    kill_timestamps.append((seconds, kill_type, x, y))

                # 어시스트 참가자인지 확인
                elif participantId in event.get('assistingParticipantIds', []):
                    kill_timestamps.append((seconds, "assist", x, y))

                # 킬에 전혀 관여하지 않은 경우, 킬러의 ID를 기록
                else:
                    kill_timestamps.append((seconds, 'other kill', x, y))

            elif event['type'] == "GAME_END":
                # 게임 종료 이벤트 추가
                end_seconds = timestamp // 1000
                kill_timestamps.append((end_seconds, "game_end", None, None))

    # 타임스탬프 리스트를 반환
    return kill_timestamps
def get_puuid_by_summoner_name(summoner_name):
    game_name, tagline = summoner_name.split('#')
    url = f"https://asia.api.riotgames.com/riot/account/v1/accounts/by-riot-id/{game_name}/{tagline}?api_key={API_KEY}"
    data = make_request_with_retries(url)

    puuid = data['puuid']
    return puuid
def get_summoner_name_by_puuid(puuid):
    url = f"https://asia.api.riotgames.com/riot/account/v1/accounts/by-puuid/{puuid}?api_key={API_KEY}"
    data = make_request_with_retries(url)

    gameName = data['gameName']
    tagLine = data['tagLine']
    return f"{gameName}#{tagLine}"
def get_tier_detail_by_puuid(puuid):
    # summonerId = get_summonerId_by_puuid(puuid)
    url = f"https://kr.api.riotgames.com/lol/league/v4/entries/by-puuid/{puuid}?api_key={API_KEY}"
    data = make_request_with_retries(url)

    # queueType이 "RANKED_SOLO_5x5"인 항목 찾기
    for entry in data:
        if entry['queueType'] == "RANKED_SOLO_5x5":
            tier = entry['tier']
            rank = entry['rank']
            leaguePoints = entry['leaguePoints']
            return f"{tier} {rank} {leaguePoints}LP"

    # "RANKED_SOLO_5x5"가 없는 경우
    return "Unranked"
def get_summonerId_by_puuid(puuid):
    url = f"https://kr.api.riotgames.com/lol/summoner/v4/summoners/by-puuid/{puuid}?api_key={API_KEY}"
    data = make_request_with_retries(url)
    # gameDuration 값 추출
    summonerId = data['id']
    return summonerId
def get_game_puuid(game_id,participantId):
    data = get_match_by_gameId(game_id)
    puuid = data['metadata']['participants'][participantId-1]
    return puuid
#테스트할때는 10초로
def get_gameDuration(game_id):
    data = get_match_by_gameId(game_id)
    game_duration = data['info']['gameDuration']
    return game_duration
    # return 10

def get_game_list_puuid(puuid):
    url = f"https://asia.api.riotgames.com/lol/match/v5/matches/by-puuid/{puuid}/ids?start=0&count=20&api_key={API_KEY}"
    data = make_request_with_retries(url)
    return data


def get_nickname_by_puuid(puuid):
    url = f"https://asia.api.riotgames.com/riot/account/v1/accounts/by-puuid/{puuid}?api_key={API_KEY}"
    data = make_request_with_retries(url)
    gameName = data['gameName']
    tagLine = data['tagLine']
    return gameName + "#" +tagLine

def is_last_game_recently_ended(puuid):
    """
    주어진 PUUID에 대해 유저의 마지막 게임이 현재 시간 기준으로 5초 이내에 종료되었는지 확인하는 함수.

    Args:
        puuid (str): 소환사의 PUUID

    Returns:
        bool: 마지막 게임이 5초 이내에 종료되었으면 True, 그렇지 않으면 False
    """
    # 헤더 설정
    headers = {
        'X-Riot-Token': API_KEY
    }

    # 최근 게임 목록 가져오기
    try:
        # get_game_list_puuid 함수가 이미 구현되어 있다고 가정
        recent_games = get_game_list_puuid(puuid)
    except Exception as e:
        print(f"최근 게임 목록을 가져오는 중 오류 발생: {e}")
        return False

    # 최근 게임이 없으면 False 반환
    if not recent_games:
        print("최근 게임이 없습니다.")
        return False

    # 마지막 게임의 match_id 가져오기 (가장 최근 게임)
    last_match_id = recent_games[0]

    # 마지막 게임의 상세 정보 가져오기
    match_url = f"https://asia.api.riotgames.com/lol/match/v5/matches/{last_match_id}?api_key={API_KEY}"
    match_data = make_request_with_retries(match_url)
    # 게임 생성 시간과 게임 지속 시간 가져오기
    game_creation = match_data.get('info', {}).get('gameCreation')  # 밀리초 단위
    game_duration = match_data.get('info', {}).get('gameDuration')  # 초 단위

    if game_creation is None or game_duration is None:
        print(f"매치 {last_match_id}의 게임 시간 정보를 찾을 수 없습니다.")
        return False

    # 게임 종료 시간 계산 (밀리초 단위)
    game_end_time_ms = game_creation + (game_duration * 1000)

    # 현재 시간 (UTC 기준, 밀리초 단위)
    current_time_utc = datetime.datetime.now(datetime.timezone.utc)
    current_timestamp_ms = int(current_time_utc.timestamp() * 1000)

    # 종료 시간과 현재 시간의 차이 계산
    time_difference_ms = current_timestamp_ms - game_end_time_ms

    # 5초(5000밀리초) 이내에 종료되었는지 확인
    if 0 <= time_difference_ms <= 5000:
        return True
    else:
        return False
def get_participants(game_id):
    headers = {'X-Riot-Token': API_KEY}
    match_url = f"https://asia.api.riotgames.com/lol/match/v5/matches/{game_id}"
    match_data = make_request_with_retries(match_url,headers)
    return match_data.get('info', {}).get('participants', [])
def get_participant_id(game_id, puuid):
    """
    주어진 game_id에서 puuid가 몇 번째 참가자인지를 반환하는 함수.

    Args:
        game_id (str): 매치 ID
        puuid (str): 소환사의 PUUID

    Returns:
        int: 참가자의 인덱스 (1~10)
        None: 참가자를 찾지 못한 경우
    """
    # 헤더 설정
    headers = {
        'X-Riot-Token': API_KEY
    }

    # 매치 데이터 가져오기
    match_url = f"https://asia.api.riotgames.com/lol/match/v5/matches/{game_id}"
    match_data = make_request_with_retries(match_url, headers)
    # 참가자 목록 가져오기
    participants = match_data.get('info', {}).get('participants', [])
    if not participants:
        print(f"매치 {game_id}의 참가자 데이터를 찾을 수 없습니다.")
        return None

    # PUUID로 참가자 찾기
    for i, participant in enumerate(participants, start=1):
        if participant.get('puuid') == puuid:
            return i  # 1-based index

    # PUUID가 참가자 목록에 없음
    print(f"매치 {game_id}에서 PUUID {puuid}의 참가자를 찾을 수 없습니다.")
    return None
if __name__ =="__main__":
    puuid = "RCUI7weq_iTer6Iwm3eZsBULJtNaL2E7IxLztxH3gr2vCZHJcNHP3TpvoB5KnMnePOdFVRN2vLAt6w"
    print(get_summoner_name_by_puuid(puuid))

    # print(get_participants("KR_7292225977"))
