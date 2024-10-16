import random
import pandas as pd
from slack_bolt.async_app import AsyncApp
import asyncio
import logging
import os

# 왓더밥김굿 (What the f..)
class LunchRecommender:
    def __init__(self, app: AsyncApp, config):
        self.app = app
        self.config = config
        self.logger = logging.getLogger(__name__)
        self.LUNCH_CSV_FILE = os.path.join(config['FILES']['csv_file_dir'], 'babzip.csv')

        # 슬래시 명령어 핸들러 등록
        app.command("/조보아씨이리와봐유")(self.handle_lunch_command)
        app.action("lunch_recommendation_한식")(self.handle_korean_food)
        app.action("lunch_recommendation_중식")(self.handle_chinese_food)
        app.action("lunch_recommendation_일식")(self.handle_japanese_food)
        app.action("lunch_recommendation_random")(self.handle_random_food)

    def read_lunch_csv(self):
        return pd.read_csv(self.LUNCH_CSV_FILE, encoding='utf-8')

    def get_random_menu(self, df, cuisine=None):
        if cuisine and cuisine != '그냥추천':
            df = df[df['구분'] == cuisine]

        if df.empty:
            return None
    
        restaurant = df.sample(n=1).iloc[0]
        menus = [restaurant['메뉴1'], restaurant['메뉴2'], restaurant['메뉴3']]
        menu = random.choice([m for m in menus if pd.notna(m)])

        return {
            '식당': restaurant['식당'],
            '메뉴': menu,
            '링크': restaurant['링크']
        }

    def create_buttons(self):
        df = self.read_lunch_csv()
        cuisines = df['구분'].unique().tolist()

        return {
            "type": "actions",
            "elements": [
                {
                    "type": "button",
                    "text": {"type": "plain_text", "text": cuisine},
                    "value": cuisine,
                    "action_id": f"lunch_recommendation_{cuisine}"
                } for cuisine in cuisines
            ] + [
                {
                    "type": "button",
                    "text": {"type": "plain_text", "text": "랜덤 돌려유?"},
                    "value": "random",
                    "action_id": "lunch_recommendation_random"
                }
            ]
        }

    # @app.command("/조보아씨이리와봐유")
    async def handle_lunch_command(self, ack, say):
        await ack()
        buttons = self.create_buttons()
        await say(
            text="장르 좀 골라봐유",
            blocks=[
                {
                    "type": "section",
                    "text": {"type": "mrkdwn", "text": ":speech_balloon: '어떤 장르로 추천해볼까유?'"}
                },
                buttons
            ]
        )

    async def show_progress(self, say):
        progress_message = await say("'메뉴 번개같이 골라줄테니께 긴장타봐유..' :thinking_face:")
        progress_emojis = [":fork_and_knife:", ":rice:", ":hamburger:", ":pizza:", ":sushi:", ":curry:", ":cut_of_meat:", ":stew:"]

        for _ in range(5):
            progress = "".join(random.choices(progress_emojis, k=random.randint(3, 6)))
            await self.app.client.chat_update(
                channel=progress_message['channel'],
                ts=progress_message['ts'],
                text=f"'메뉴 번개같이 골라줄테니께 긴장타봐유..' {progress}"
            )
            await asyncio.sleep(random.uniform(0.2, 0.5))
    
        return progress_message

    async def handle_cuisine_selection(self, body, say, cuisine):
        progress_message = await self.show_progress(say)

        df = self.read_lunch_csv()
        recommendation = self.get_random_menu(df, cuisine)

        if recommendation:
            await self.app.client.chat_update(
                channel=progress_message['channel'],
                ts=progress_message['ts'],
                text="추천헐께유",
                blocks=[
                    {
                        "type": "section",
                        "text": {"type": "mrkdwn", "text": f":speech_balloon: '오늘은 *{recommendation['식당']}* 가서 *{recommendation['메뉴']}* 한번 씹어봐유'"}
                    },
                    {
                        "type": "actions",
                        "elements": [
                            {
                                "type": "button",
                                "text": {"type": "plain_text", "text": "어딘지 모르면 눌러봐유"},
                                "url": recommendation['링크']
                            }
                        ]
                    }
                ]
            )
    
            await say(
                text="추천은 맘에 드는겨?",
                blocks=[
                    {
                        "type": "section",
                        "fields": [
                            {
                                "type": "mrkdwn",
                                "text": ":speech_balloon: '추천은 맘에 드는겨?'"
                            },
                            {
                                "type": "mrkdwn",
                                "text": " "    # 빈칸으로 레이아웃 조정
                            }
                        ]
                    },
                    {
                        "type": "actions",
                        "elements": [
                            {
                                "type": "button",
                                "text": {"type": "plain_text", "text": "한번 더혀?"},
                                "action_id": "lunch_recommendation_random"
                            }
                        ]
                    }
                ]
            )
        else:
            await self.app.client.chat_update(
                channel=progress_message['channel'],
                ts=progress_message['ts'],
                text=f"{cuisine} 메뉴가 읍는디?"
            )

    # @app.action("lunch_recommendation_한식")
    async def handle_korean_food(self, ack, body, say):
        await ack()
        await self.handle_cuisine_selection(body, say, '한식')

    # @app.action("lunch_recommendation_중식")
    async def handle_chinese_food(self, ack, body, say):
        await ack()
        await self.handle_cuisine_selection(body, say, '중식')

    # @app.action("lunch_recommendation_일식")
    async def handle_japanese_food(self, ack, body, say):
        await ack()
        await self.handle_cuisine_selection(body, say, '일식')

    # @app.action("lunch_recommendation_random")
    async def handle_random_food(self, ack, body, say):
        await ack()
        await self.handle_cuisine_selection(body, say, None)

def init(app: AsyncApp, config):
    LunchRecommender(app, config)