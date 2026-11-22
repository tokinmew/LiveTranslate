"""Source profiles for the checked NLLB vocabulary and local Whisper models.

The first column is the app's public ID; the second is the exact model token.
Each row is a selectable written variety. English is the destination only.
"""

_GROUPS = {
    "Asia": """
zt zho_Hant Chinese (Traditional)
zh zho_Hans Chinese (Simplified)
ja jpn_Jpan Japanese
ko kor_Hang Korean
yue yue_Hant Cantonese (Traditional)
ace ace_Latn Acehnese (Latin)
ace-arab ace_Arab Acehnese (Arabic script)
acm acm_Arab Arabic (Mesopotamian)
acq acq_Arab Arabic (Ta'izzi-Adeni)
ajp ajp_Arab Arabic (South Levantine)
apc apc_Arab Arabic (North Levantine)
ar arb_Arab Arabic (Modern Standard)
ars ars_Arab Arabic (Najdi)
as asm_Beng Assamese
awa awa_Deva Awadhi
azb azb_Arab Azerbaijani (South)
az azj_Latn Azerbaijani (North)
ba bak_Cyrl Bashkir
ban ban_Latn Balinese
bn ben_Beng Bengali
bho bho_Deva Bhojpuri
bjn bjn_Latn Banjar (Latin)
bjn-arab bjn_Arab Banjar (Arabic script)
bo bod_Tibt Tibetan
bug bug_Latn Buginese
ceb ceb_Latn Cebuano
ckb ckb_Arab Kurdish (Central)
dz dzo_Tibt Dzongkha
fa pes_Arab Persian (Iranian)
gu guj_Gujr Gujarati
he heb_Hebr Hebrew
hi hin_Deva Hindi
hne hne_Deva Chhattisgarhi
hy hye_Armn Armenian
ilo ilo_Latn Ilocano
id ind_Latn Indonesian
jv jav_Latn Javanese
kac kac_Latn Jingpho
kn kan_Knda Kannada
ks kas_Arab Kashmiri (Arabic script)
ks-deva kas_Deva Kashmiri (Devanagari)
ka kat_Geor Georgian
kk kaz_Cyrl Kazakh
km khm_Khmr Khmer
ky kir_Cyrl Kyrgyz
kmr kmr_Latn Kurdish (Northern)
lo lao_Laoo Lao
lus lus_Latn Mizo
mag mag_Deva Magahi
mai mai_Deva Maithili
ml mal_Mlym Malayalam
mr mar_Deva Marathi
min min_Latn Minangkabau
mni mni_Beng Manipuri (Meitei, Bengali script)
mn khk_Cyrl Mongolian (Halh)
ms zsm_Latn Malay (Standard)
my mya_Mymr Burmese
ne npi_Deva Nepali
or ory_Orya Odia
pag pag_Latn Pangasinan
pa pan_Guru Punjabi (Gurmukhi)
prs prs_Arab Dari
ps pbt_Arab Pashto (Southern)
sa san_Deva Sanskrit
sat sat_Beng Santali (Bengali script)
shn shn_Mymr Shan
si sin_Sinh Sinhala
sd snd_Arab Sindhi
su sun_Latn Sundanese
ta tam_Taml Tamil
tt tat_Cyrl Tatar
te tel_Telu Telugu
tg tgk_Cyrl Tajik
tl tgl_Latn Tagalog
th tha_Thai Thai
tk tuk_Latn Turkmen
tr tur_Latn Turkish
ug uig_Arab Uyghur
ur urd_Arab Urdu
uz uzn_Latn Uzbek (Northern)
vi vie_Latn Vietnamese
war war_Latn Waray
""",
    "Europe": """
ast ast_Latn Asturian
be bel_Cyrl Belarusian
bs bos_Latn Bosnian
bg bul_Cyrl Bulgarian
ca cat_Latn Catalan
cs ces_Latn Czech
crh crh_Latn Crimean Tatar
cy cym_Latn Welsh
da dan_Latn Danish
de deu_Latn German
el ell_Grek Greek
eo epo_Latn Esperanto
et est_Latn Estonian
eu eus_Latn Basque
fo fao_Latn Faroese
fi fin_Latn Finnish
fr fra_Latn French
fur fur_Latn Friulian
gd gla_Latn Scottish Gaelic
ga gle_Latn Irish
gl glg_Latn Galician
hr hrv_Latn Croatian
hu hun_Latn Hungarian
is isl_Latn Icelandic
it ita_Latn Italian
lv lvs_Latn Latvian (Standard)
lij lij_Latn Ligurian
li lim_Latn Limburgish
lt lit_Latn Lithuanian
lmo lmo_Latn Lombard
ltg ltg_Latn Latgalian
lb ltz_Latn Luxembourgish
mk mkd_Cyrl Macedonian
mt mlt_Latn Maltese
nl nld_Latn Dutch
nn nno_Latn Norwegian (Nynorsk)
no nob_Latn Norwegian (Bokmål)
oc oci_Latn Occitan
pl pol_Latn Polish
pt por_Latn Portuguese
ro ron_Latn Romanian
ru rus_Cyrl Russian
scn scn_Latn Sicilian
sk slk_Latn Slovak
sl slv_Latn Slovenian
es spa_Latn Spanish
sq als_Latn Albanian (Tosk)
sc srd_Latn Sardinian
sr srp_Cyrl Serbian (Cyrillic)
sv swe_Latn Swedish
szl szl_Latn Silesian
uk ukr_Cyrl Ukrainian
vec vec_Latn Venetian
yi ydd_Hebr Yiddish (Eastern)
""",
    "Africa": """
aeb aeb_Arab Arabic (Tunisian)
af afr_Latn Afrikaans
ak aka_Latn Akan
am amh_Ethi Amharic
ary ary_Arab Arabic (Moroccan)
arz arz_Arab Arabic (Egyptian)
bm bam_Latn Bambara
bem bem_Latn Bemba
cjk cjk_Latn Chokwe
dik dik_Latn Dinka (Southwestern)
dyu dyu_Latn Dyula
ee ewe_Latn Ewe
fon fon_Latn Fon
fuv fuv_Latn Fulfulde (Nigerian)
ha hau_Latn Hausa
ig ibo_Latn Igbo
kab kab_Latn Kabyle
kam kam_Latn Kamba
knc knc_Latn Kanuri (Central, Latin)
knc-arab knc_Arab Kanuri (Central, Arabic script)
kbp kbp_Latn Kabiyè
kea kea_Latn Cape Verdean Creole
ki kik_Latn Kikuyu
rw kin_Latn Kinyarwanda
kmb kmb_Latn Kimbundu
kg kon_Latn Kongo
ln lin_Latn Lingala
lua lua_Latn Luba-Kasai
lg lug_Latn Ganda
luo luo_Latn Luo
mg plt_Latn Malagasy (Plateau)
mos mos_Latn Mossi
nso nso_Latn Northern Sotho
nus nus_Latn Nuer
ny nya_Latn Chichewa
om gaz_Latn Oromo (West Central)
rn run_Latn Rundi
sg sag_Latn Sango
sn sna_Latn Shona
so som_Latn Somali
st sot_Latn Southern Sotho
ss ssw_Latn Swati
sw swh_Latn Swahili
ti tir_Ethi Tigrinya
taq taq_Latn Tamasheq (Latin)
taq-tfng taq_Tfng Tamasheq (Tifinagh)
tn tsn_Latn Tswana
ts tso_Latn Tsonga
tum tum_Latn Tumbuka
tw twi_Latn Twi
tzm tzm_Tfng Tamazight (Central Atlas)
umb umb_Latn Umbundu
wo wol_Latn Wolof
xh xho_Latn Xhosa
yo yor_Latn Yoruba
zu zul_Latn Zulu
""",
    "Americas": """
ay ayr_Latn Aymara (Central)
gn grn_Latn Guarani
ht hat_Latn Haitian Creole
pap pap_Latn Papiamento
qu quy_Latn Quechua (Ayacucho)
""",
    "Oceania": """
fj fij_Latn Fijian
mi mri_Latn Māori
sm smo_Latn Samoan
tpi tpi_Latn Tok Pisin
""",
}

NLLB_TAGS = {}
LANGUAGE_NAMES = {}
REGIONS = {}
for _region, _rows in _GROUPS.items():
    for _row in _rows.strip().splitlines():
        _code, _tag, _name = _row.split(' ', 2)
        NLLB_TAGS[_code] = _tag
        LANGUAGE_NAMES[_code] = _name
        REGIONS[_code] = _region

# Whisper also translates a few spoken languages outside the NLLB vocabulary.
for _code, _name, _region in (
    ('br', 'Breton', 'Europe'), ('haw', 'Hawaiian', 'Oceania'),
    ('la', 'Latin', 'Europe'), ('lb', 'Luxembourgish', 'Europe'),
    ('ln', 'Lingala', 'Africa'), ('mi', 'Māori', 'Oceania'),
):
    LANGUAGE_NAMES.setdefault(_code, _name)
    REGIONS.setdefault(_code, _region)

# Accepted identifiers from OS locale lists, detectors and imported packs.
ALIASES = {'nb': 'no', 'iw': 'he', 'in': 'id', 'jw': 'jv', 'fil': 'tl',
           'zh-hans': 'zh', 'zh-cn': 'zh', 'zh-sg': 'zh', 'zh-hant': 'zt',
           'zh-tw': 'zt', 'zh-hk': 'zt', 'zh-mo': 'zt', 'ku': 'kmr',
           'fa-ir': 'fa', 'fa-af': 'prs'}

def canonical_code(code):
    code = str(code or '').strip().lower().replace('_', '-')
    if code in ALIASES:
        return ALIASES[code]
    if code in LANGUAGE_NAMES or '-' not in code:
        return code
    stem = code.partition('-')[0]
    return stem if stem in LANGUAGE_NAMES else code

