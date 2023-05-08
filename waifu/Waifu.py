import json
import waifu.Thoughts
from waifu.Tools import make_message, message_period_to_now
from langchain.schema import messages_from_dict, messages_to_dict
from langchain.chains.summarize import load_summarize_chain
from langchain.docstore.document import Document
from langchain.prompts.chat import PromptTemplate
from langchain.schema import AIMessage, HumanMessage, SystemMessage
from langchain.memory import ChatMessageHistory
import logging

class Waifu():
    '''CyberWaifu'''

    def __init__(self, brain, prompt, name, use_search = False, search_api = '', use_emoji = True, use_emoticon = True):
        self.brain = brain
        self.name = name
        self.charactor_prompt = SystemMessage(content=f'{prompt}\nYour name is "{name}". Do not response with "{name}: xxx"')
        self.chat_memory = ChatMessageHistory()
        self.history = ChatMessageHistory()
        self.waifu_reply = ''

        self.use_emoji = use_emoji
        self.use_emoticon = use_emoticon
        self.use_search = use_search
        self.emoji = waifu.Thoughts.AddEmoji(self.brain)
        self.emoticon = waifu.Thoughts.SendEmoticon(self.brain)
        self.search = waifu.Thoughts.Search(self.brain, search_api)

        self.load_memory()


    def ask(self, text):
        '''发送信息'''
        message = make_message(text)
        # 第一次检查用户输入文本是否过长
        if self.brain.llm.get_num_tokens_from_messages([message]) >= 256:
            raise ValueError('The text is too long!')
        # 第二次检查 历史记录+用户文本 是否过长
        if self.brain.llm.get_num_tokens_from_messages([message])\
                + self.brain.llm.get_num_tokens_from_messages(self.chat_memory.messages)>= 1536:
            self.summarize_memory()
        # 第三次检查，如果仍然过长，暴力裁切记忆
        while self.brain.llm.get_num_tokens_from_messages([message])\
                + self.brain.llm.get_num_tokens_from_messages(self.chat_memory.messages)>= 1536:
            self.cut_memory()

        messages = [self.charactor_prompt]

        logging.info(f'开始！接收到信息: {text}')

        # 相关记忆
        relative_memory = self.brain.extract_memory(text)

        is_full = False
        total_token = 0
        for i in range(len(relative_memory)):
            total_token += self.brain.llm.get_num_tokens(relative_memory[i])
            if(total_token >= 1024):
                is_full = True
        if is_full:
            relative_memory = relative_memory[:i]

        if len(relative_memory) > 0:
            memory_prompt = f'This following message is relative context for your response:\n\n{str(relative_memory)}'
            memory_message = SystemMessage(content=memory_prompt)
            messages.append(memory_message)

            logging.debug(f'相关记忆:\n' + '\n'.join([str(elem) for elem in relative_memory]))

        # 事实搜索
        question, answer = self.search.think(text)
        if not answer == '':
            logging.info(f'进行搜索:\nQuestion: {question}\nAnswer:{answer}')
            fact_prompt = f'This following message is relative context searched in Google:\nQuestion:{question}\nAnswer:{answer}'
            fact_message = SystemMessage(content=fact_prompt)
            messages.append(fact_message)

        # 系统信息
        if len(self.chat_memory.messages) >= 2:
            duration = message_period_to_now(self.chat_memory.messages[-2])
            if duration > 1.0:
                system_message = SystemMessage(content=f'Passed {duration} hours since last conversation. You should simulate what you are doing during this period or make corresponding chat responses based on changes in time.')
                messages.append(system_message)
                logging.debug(f'引入系统信息: {system_message.content}')

        # 发送消息
        self.chat_memory.messages.append(message)
        self.history.messages.append(message)
        messages.extend(self.chat_memory.messages)
        while self.brain.llm.get_num_tokens_from_messages(messages) > 4096:
            self.cut_memory()
        self.brain.think(messages)

        history = []
        for message in self.chat_memory.messages:
            if isinstance(message, HumanMessage):
                history.append(f'用户: {message.content}')
            else:
                history.append(f'Waifu: {message.content}')
        info = '\n'.join(history)
        logging.debug(f'上下文记忆:\n{info}')

        if self.brain.llm.get_num_tokens_from_messages(self.chat_memory.messages)>= 2048:
            self.summarize_memory()

        logging.info('结束回复')


    def finish_ask(self, text):
        self.chat_memory.add_ai_message(text)
        self.history.add_ai_message(text)
        self.save_memory()
        if self.use_emoticon:
            file = self.emoticon.think(text)
            logging.info(f'发送表情包: {file}')
            return file
        else:
            return ''


    def add_emoji(self, text):
        if self.use_emoji:
            emoji = self.emoji.think(text)
            return emoji
        else:
            return ''


    def import_memory_dataset(self, text):
        '''导入记忆数据库, text 是按换行符分块的长文本'''
        chunks = text.split('\n\n')
        self.brain.store_memory(chunks)


    def save_memory_dataset(self, memory):
        '''保存至记忆数据库, memory 可以是文本列表, 也是可以是文本'''
        self.brain.store_memory(memory)


    def load_memory(self):
        '''读取历史记忆'''
        try:
            with open(f'./memory/{self.name}.json', 'r', encoding='utf-8') as f:
                dicts = json.load(f)
                self.chat_memory.messages = messages_from_dict(dicts)
                self.history.messages = messages_from_dict(dicts)
                while len(self.chat_memory.messages) > 6:
                    self.chat_memory.messages.pop(0)
                    self.chat_memory.messages.pop(0)
        except FileNotFoundError:
            pass


    def cut_memory(self):
        '''删除一轮对话'''
        for i in range(2):
            first = self.chat_memory.messages.pop(0)
            logging.debug(f'删除上下文记忆: {first}')


    def save_memory(self):
        '''保存记忆'''
        dicts = messages_to_dict(self.history.messages)
        with open(f'./memory/{self.name}.json', 'w',encoding='utf-8') as f:
            json.dump(dicts, f, ensure_ascii=False)


    def summarize_memory(self):
        '''总结 chat_memory 并保存到记忆数据库中'''
        docs = []
        for t in self.chat_memory.messages:
            if isinstance(t, HumanMessage):
                docs.append(Document(page_content=f'用户:{t.content}'))
            elif isinstance(t, AIMessage):
                docs.append(Document(page_content=f'{self.name}:{t.content}'))
        prompt_template = """Write a concise summary of the following, time information should be include:


        {text}


        CONCISE SUMMARY IN CHINESE LESS THAN 300 TOKENS:"""
        PROMPT = PromptTemplate(template=prompt_template, input_variables=["text"])
        chain = load_summarize_chain(self.brain.llm_nonstream, chain_type="stuff", prompt=PROMPT)
        summary = chain.run(docs)
        while len(self.chat_memory.messages) > 4:
            self.cut_memory()
        self.save_memory_dataset(summary)
        logging.info(f'总结记忆: {summary}')