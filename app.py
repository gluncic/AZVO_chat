# app.py
import os
import uuid
from fastapi import Request, Response
from dotenv import load_dotenv
from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from langchain_openai import OpenAIEmbeddings, ChatOpenAI
from langchain_chroma import Chroma
from langchain_core.prompts import ChatPromptTemplate, PromptTemplate
from langchain_core.output_parsers import StrOutputParser
import json
from format_ispisa import format_lists_to_html
from fastapi.responses import HTMLResponse

load_dotenv()
API_KEY = os.getenv("OPENAI_API_KEY")
app = FastAPI()
templates = Jinja2Templates(directory="templates")

embedding = OpenAIEmbeddings(api_key=API_KEY)
vectordb = Chroma(persist_directory='./azvo_baza', collection_name='clanci_novo', embedding_function=embedding)
vectordb2 = Chroma(persist_directory='./azvo_baza', collection_name='pitanja', embedding_function=embedding)
with open("kalendari_raspakirani.json", "r") as f: kalendar = json.load(f)

retriever = vectordb.as_retriever(search_type='similarity', search_kwargs={'k': 10})
retriever2 = vectordb2.as_retriever(search_type='similarity', search_kwargs={'k': 10})

prompt = ChatPromptTemplate.from_template( """
        Ti si pomoćnik koji pomaže ljudima s informacijama o upisu na fakultet.

        Dobit ćeš sljedeće:
        - Postavljeno pitanje: {query}
        - Članke iz pravilnika o upisu na fakultet: {clanci}
        - Popis često postavljanih pitanja s odgovorima: {pitanja}
        - Kalendar s važnim datumima: {kalendar}

        Tvoj zadatak je:
        - Odgovoriti isključivo na temelju danih izvora.
        - Ako koristiš informaciju iz pravilnika, obavezno navedi broj članka iz kojeg je ta informacija preuzeta.
        - Nemoj navoditi iz kojeg je dijela 'često postavljanih pitanja' nešto preuzeto – samo koristi informaciju.
        - Nikada ne odgovaraj na pitanja čije odgovore ne možeš naći u izvorima. Ako nešto nije navedeno u pravilniku, pitanjima ili kalendaru, reci: "Nemam točnu informaciju, preporučujem da provjerite službene izvore."
        - Posebno pazi na razliku između **prediplomskog** i **diplomskog** studija – pravila za njih nisu ista.
        - Odgovaraj na jeziku na kojem je pitanje postavljeno.
        - Ne spominji asistenta ili način na koji si došao do informacije – odgovaraj prirodno, kao da razgovaraš s osobom.
        - Ako se u pitanju traži datum, godina ili vremenski rok, isključivo provjeri kalendar – tamo će uvijek biti tražena informacija.
        - Ako koristiš odgovor iz kalendaru uvijek naglasi o kojem se studiju radi i o kojem roku. 
        - Ako pitanje odgovara za više studija i više rokova neka odgovor sadrži dio za svaku vrstu studija (prijediplomski prvi rok, prijediplomski drugi rok i diplomski).
        - Ako u odgovoru koristiš popis s crticama (-) ili brojevima (1., 2., ...), svaki element popisa mora biti u novom retku — nikad sve u jednoj rečenici.
 
        Primarni cilj je dati točan i koristan odgovor, temeljen isključivo na dostupnim izvorima.
    """
)
llm = ChatOpenAI(model="gpt-4o", api_key=API_KEY, temperature=0)
chain = prompt | llm | StrOutputParser()
# Sesijska memorija po korisniku
user_sessions = {}

# Glavna stranica
@app.get("/", response_class=HTMLResponse)
def root(request: Request):
    return templates.TemplateResponse("index.html", {"request": request})

#Cchat komunikacija
@app.post("/chat")
async def chat(request: Request):
    data = await request.json()
    q = data.get("question", "").strip()
    # Dohvati session_id iz cookie-a ili generiraj novi
    session_id = request.cookies.get("session_id")
    if not session_id:
        session_id = str(uuid.uuid4())

    last_q = user_sessions.get(session_id)
    q_hr, language = what_language(q)

    full_q = make_summary(last_q, q_hr) if last_q and is_followup_question(last_q, q_hr) else q_hr

    clanci = retriever.invoke(full_q)
    pitanja = retriever2.invoke(full_q)
    kalendar_input = filter_kalendara(full_q)
    answer = chain.invoke({'query': full_q, 'clanci': clanci, 'pitanja': pitanja, 'kalendar': kalendar_input})

    if language != 'HR':
        answer = translate(answer, language)

     # Spremi novi kontekst
    user_sessions[session_id] = full_q
    formatted = format_lists_to_html(answer)
    response = JSONResponse(content={"answer": answer, "formatted": formatted})
    response.set_cookie("session_id", session_id)
    return response

#****************************************************************************************************
# --- POMOĆNE FUNKCIJE  ---
#****************************************************************************************************
def is_followup_question(last, new):
    if new.lower().strip().startswith(('a ', 'a što', 'a ako', 'a kad', 'a u', 'a za')):
        return True
    p = PromptTemplate.from_template(
            "Korisnik vodi razgovor s AI asistentom.\n"
            "Zadnje pitanje korisnika bilo je:\n\"{last}\"\n"
            "Novo pitanje korisnika je:\n\"{new}\"\n\n"
            "Je li drugo pitanje nastavak prvog (nastavlja istu temu, implicitno je povezano, koristi 'a', 'a ako', 'a što', itd.)?\n"
            "Odgovori samo: DA ili NE"
    )
    model = ChatOpenAI(model="gpt-4o", api_key=API_KEY, temperature=0)
    c = p | model | StrOutputParser()
    return c.invoke({"last": last, "new": new}).strip().upper().startswith("DA")

#****************************************************************************************************
def make_summary(last, new):
    p = PromptTemplate(input_variables=['memory', 'query'], template=
                        "Korisnik je prethodno postavio pitanje: \"{memory}\"\n"
                        "Sada postavlja novo pitanje: \"{query}\"\n\n"
                        "Ako je novo pitanje nepotpuno, tvoj je zadatak reformulirati ga u potpuno, jasno pitanje, "
                        "koristeći prethodni kontekst. Ako je novo pitanje već potpuno i jasno, samo ga ponovi bez ikakvih izmjena.\n\n"
                        "Vrati isključivo reformulirano pitanje, bez dodatnih komentara ili objašnjenja."
    )
    c = p | ChatOpenAI(model="gpt-4o", api_key=API_KEY, temperature=0) | StrOutputParser()
    return c.invoke({'memory': last, 'query': new}).strip()

#****************************************************************************************************
def filter_kalendara(q):
    p = PromptTemplate(input_variables=['query'], template=
                        "Za ovo pitanje: \"{query}\"\n"
                        "odluči pripada li:\n"
                        "- prijediplomskom studijskom programu ili\n"
                        "- diplomskom studijskom programu.\n\n"
                        "Ako se odnosi na prijediplomski, napiši i je li prvi ili drugi rok.\n"
                        "Format odgovora treba biti:\n"
                        "prijediplomski &&& prvi\n"
                        "ili\n"
                        "prijediplomski &&& drugi\n"
                        "ili\n"
                        "diplomski\n"
                        # "Ako se ne može odrediti, odgovori samo s: prijediplomski &&& prvi\n"
                        "Isključivo ako smatraš da pitanje nije povezano s datumom ili bilo kojim vremenskim rokom i da ne pripada kalendaru odgovori s: NE\n"
                        "Nemoj dodavati nikakva dodatna objašnjenja."
                           )
    c = p | ChatOpenAI(model="gpt-4o", api_key=API_KEY) | StrOutputParser()
    answer = c.invoke({'query': q}).strip().lower()
    if answer == "NE":
        return []
    if "prijediplomski" in answer and "&&&" in answer:
        tip, rok = [part.strip() for part in answer.split("&&&")]
        return [dio_kal for dio_kal in kalendar if dio_kal['tip'] == "prijediplomski" and dio_kal['rok'] == rok]
    if answer == "diplomski":
        return [dio_kal for dio_kal in kalendar if dio_kal['tip'] == "diplomski"]
    return kalendar

#****************************************************************************************************
def what_language(q):
    prompt=PromptTemplate(input_variables=['query'],
                          template="Dobiti ćeš text:{query}, i tvoj je zadatak odrediti na kojem je jeziku napisan tekst"
                                   "te ga prevesti na hrvatski jezik ako nije napisan na hrvatskom jeziku. Razdvoji ime jezika i prijevod s &&&. Napiši ime jezika na hrvatskom."
                                   "Ako je pitanje napisano na hrvatskom jeziku odgovori samo s HR."
                          )
    llm=ChatOpenAI(model = "gpt-4o", api_key = API_KEY)
    chain = prompt | llm | StrOutputParser()
    x=chain.invoke({'query':q})
    x=x.split('&&&')
    if len(x)==1:
        return q,"HR"
    else:
        return x[1],x[0]

#***********************************************************************************************************************
def translate(text,lang):
    prompt=PromptTemplate(input_variables=['text','language'],
                          template="Tvoj zadatak je prevesti ovaj text:{text} na ovaj jezik:{language}."
                                   "Napiši samo prijevod nemoj pisati nikakve dodatne komentare."
                          )
    llm = ChatOpenAI(model = "gpt-4o", api_key = API_KEY)
    chain = prompt | llm | StrOutputParser()
    x = chain.invoke({'text': text, 'language': lang})
    return x

#***********************************************************************************************************************



