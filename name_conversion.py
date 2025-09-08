import json

def get_real_champion_name(champion_name, language = "en"):
    if language == "ko":
        with open('champion_names_ko.json', 'r', encoding='utf-8') as file:
            name_conversion = json.load(file)
    else:
        with open('champion_names_en.json', 'r', encoding='utf-8') as file:
            name_conversion = json.load(file)

    return name_conversion[champion_name]

def get_position_name(lane, language = "en"):
    if language =="ko":
        if lane == "top":
            return "탑"
        elif lane == "jungle":
            return "정글"
        elif lane == "mid":
            return "미드"
        elif lane == "adc":
            return "원딜"
        elif lane == "support":
            return "서폿"
    else:
        return lane.capitalize()

if __name__ =="__main__":
    print(get_real_champion_name("Khazix","en"))