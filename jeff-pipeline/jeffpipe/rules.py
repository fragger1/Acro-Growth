"""Every filter rule for Jeff's leads, in one place.

Copied from the dated scripts that used to carry them (clean_leads.py 10/01, build_pool.py 10/05-10/06,
JeffBackfill 10/07, clean_run17.py 10/07, clean_batch2.py 10/09, JeffLeads 10/11, JeffRerun 10/15) and
checked equal to them by tests/test_rules_parity.py. Change a rule here, never in a run folder.

What a place has to pass (place_reason / reason):
  not a roofer, not government or a public school, not a national chain or franchise (name or domain),
  not mobile-only or an in-home daycare, not a home-service trade (10/06: 0 human replies from ~130),
  not an office / medical / salon tenant, has a Google address (blank = home-based) unless it manages
  property, is in one of Jeff's cities AND in KS or MO, its domain is not already in PlusVibe or
  delivered, not a small-roof / tenant type, not renting a suite or unit (property managers excepted),
  and (new 10/15) not a school district site (usd497.org) or a place whose inbox is .gov / .mil / k12.
The pools step also keeps only places within config.POOL_RADIUS miles of Jeff.

What an email has to be (own_email / pick_email): on the business's own website domain if it has one,
not a personal or ISP inbox (gmail, kc.rr.com ...), not junk (font credits, web builders, placeholders,
no-reply) and not a junk role inbox (careers, hr, press, billing ...). A place whose email fails this is
not dropped: it goes to the generic-inbox guess on its own domain instead.

Off-target categories (2026-10-15 rule): email an off-target business only when the shop is most likely
owned by the person running it (owner_run).
"""
import re

# Jeff's service area: his website cities, the towns within 30 miles (confirmed 2026-09-30) and the 9
# towns added 2026-10-09. city_of() compares names only, so place_reason also requires KS or MO.
AREA = {
    # Jeff's website cities
    "olathe", "shawnee", "mission hills", "roeland park", "prairie village", "lenexa", "fairway",
    "paola", "leawood", "edgerton", "gardner", "ottawa", "spring hill", "kansas city", "lawrence",
    "overland park", "merriam", "mission", "bonner springs", "raytown", "parkville",
    "north kansas city", "lees summit", "blue springs", "platte city", "belton", "grandview",
    "riverside", "independence", "shawnee mission", "rosedale",
    # within 30 miles (confirmed 2026-09-30)
    "stilwell", "bucyrus", "de soto", "edwardsville", "hillsdale", "linwood", "eudora",
    "louisburg", "basehor", "wellsville", "tonganoxie", "la cygne", "baldwin city", "lansing",
    "rantoul", "osawatomie", "lake quivira", "gladstone", "sugar creek", "raymore", "peculiar",
    "cleveland", "freeman", "greenwood", "lake winnebago", "lake lotawana", "drexel", "farley",
    "harrisonville", "pleasant hill",
    "lacygne",  # spelling variant of La Cygne
    # towns added 2026-10-09 (run 19, within the 45-mile export radius)
    "liberty", "kearney", "smithville", "excelsior springs", "pleasant valley",
    "grain valley", "oak grove", "buckner", "leavenworth",
}
STATES = ("kansas", "missouri", "ks", "mo")

# ---------------------------------------------------------------- chains, platforms, government
# National / big regional brands, matched on the website's root label (homedepot.com -> homedepot).
CHAINS = set("""
1aauto 48forty abcsupply acehardware acrisure adidas advanceautoparts adventhealth airgas airgeneral
aldi allegroliving alphagraphics amcor americold anthemmemorycare apartments apria arcticglacier
ashgrove assaabloy assaabloydss assistrx atd att attic-storage avnet baader baskinrobbins
berkshirehathawayautomotive berryglobal bestwashlaundromats bhhs bigotires bioivt bldr bluerhino
bomgaars bp budgetblinds buick bungalow burlington cadence-education caliber californiaclosets
campingworld carenow carrier carrierenterprise carstar caseys catalent century21 certainteed
cfa-supply chevyusa chewy churchofjesuschrist cintas coldstonecreamery coldwellbanker comforcare
compass coreandmain cosentino costco crc cubesmart cvs cyclegear dawnfoods daytonsuperior dhl
dickssportinggoods dignitymemorial dillons discounttire doitbest dollargeneral dsw elanco
elliottelectric enterprise exp exprealty expressoil extraspace farmers fastenal fastsigns fbfs fedex
fedexfreight ferguson fergusonhome ferrellgas fetchpackage firestonecompleteautocare fivebelow
flexsteel flooranddecor floorcoveringsinternational ford fritolay fuchs fullypromoted gm gocarwash
goddardschool good-sam goodfeet grainger gxo halo handymanconnection heartlandcocacola henhouse
hobbylobby homedepot humanscale hy-vee iff ihg ikea imospizza imperialdade industrialnetworking
ingredion intoxalock iqvia itlchicago jasperengines jbhunt jcpenney jiffylube johnstonesupply
justselfstorage kellerwilliams kelloggs kgstores kkwindsolutions kohls kw la-z-boy lapetite lcca
legendseniorliving life lifesafer lincare lowcostinterlock lowes maac mannapro marriott mars
marshalls mattressfirm maxonamerica mcnichols meineke menards menswearhouse merck-animal-health-usa
mhc michaels momento montessori moovelube multivac mypricechopper neighbor northamerican
nothingbundtcakes officedepot oreillyauto owens-minor owenscorning palletone panasonic parkson
pentair phillips66fuels pompstire postconsumerbrands potbelly potterybarn prattindustries praxair
primroseschools proforma progressrail prpwine publicstorage questevents quiktrip rackroomshoes
radiator rallyhouse realtyexecutives recnationstorage redfin reecenichols regalgift remax
republicservices rti-inc rxo sallybeauty salvationarmy samsclub scheuchna scooterscoffee
sherwin-williams siteboxstorage skechers slb smartstartinc speedpro springslivingop ssactivewear
staples starbucks storage-mart storagesense stortropolis stratussurfaces stretchzone sulekha
sunbeltrentals sunriseseniorliving sutherlands systemair target tecovas ten theupsstore thryv
tileshop timken titanlogix tractorsupply trekbikes truevalue tuffshed ubc ufppackaging uhaul
unitedrentals ups usfoods veseris visualcomfort vortexdoors w-d walgreens walmart westlakehardware
whitecap winlandfoods winsupplyinc yescommunities youradv zillow ziwipets
""".split())

# Chain, franchise and corporate domains (build_pool CHAIN_DOMAINS 10/06 + backfill EXTRA_CHAIN_DOMAINS 10/07).
CHAIN_DOMAINS = set("""
24hourfitness.com 9round.com aaon.com adidas.com alliedvan.com anytimefitness.com avis.com
banfield.com barre3.com bluebuff.com bluepearlvet.com blushfitness.com bodyfittraining.com
brighthorizons.com burnbootcamp.com cabinetiq.com caliber.com campbowwow.com carestreet.com
childcareofamerica.com childrenslighthouse.com cleaneatz.com clubpilates.com creativeworldschool.com
crunch.com cubesmart.com culvers.com cyclebar.com datamyx.com discounttire.com dogtopia.com
equipmentshare.com extraspace.com f45training.com fergusonhome.com firstwash.com galls.com
gatewayclassiccars.com genesishealthclubs.com goddardschool.com goddardsystems.com goodfeet.com
goodvets.com goodyear.com honeywell.com hooters.com hoshizaki.com icehouseamerica.com ikea.com
jazzercise.com jmsmucker.com jovie.com kgstores.com kiddieacademy.net kindercare.com ku.edu
lafitness.com lapetite.com learningcareinc.com linde.com livebh.com livelmh.com loewshotels.com
mckesson.com mindbodyonline.com missionrockresidential.com myplacehotels.com navl.com neighbor.com
nkcschools.org nva.com olatheschools.org orangetheory.com oxfordseniorliving.com petco.com
phillipsedison.com planetfitness.com primroseschools.com publicstorage.com puregym.com
rallyhouse.com reecenichols.com rnrtires.com sirva.com smsd.org snapfitness.com springhillrec.org
stcroixhospice.com sunriseseniorliving.com tecovas.com therowhouse.com theupsstore.com
thrivepetcare.com titleboxingclub.com trailersplus.com tutortime.com unitedrealestate.com
upwards.com vagaro.com vcahospitals.com warehousequote.com woofsplaystay.com yescommunities.com
""".split())
# National companies, corporate / platform / lead-gen domains from the 10/05 and 10/07 hand reviews
# (backfill review.py NATIONAL). Also never taken as a place's own email.
REVIEW_NATIONAL = set("""
agendausa.com allmysons.com antolin.com bc.com berryplastics.com boxerproperty.com buckeye.com
buykratombulkusa.com cabinetstogo.com car-mart.com cargolargo.com carofferly.com carwise.com
cashforcars-junkcars.net chg.com churchtrac.com cityofedgerton.org closetfactory.com
closetsbydesign.com conklin.com crown.com customtruck.com desotoks.us elks.org expeditors.com
fastsigns.com forbo.com forwardair.com gallagher.com godrevealsclothing.com gprstaffing.com
hacls.org hbfuller.com healthmateforever.com highwoods.com homestead.com horizonglobal.com hq.com
huhtamaki.com hyatt.com image360.com impelunion.com innomotics.com isolatek.com kansascityymca.org
lairdplastics.com landcare.com lansingks.org lawnlove.com leisurehotel.com lkqcorp.com macdon.com
mactac.com marten.com mclaneco.com mechanix.com minutemanlawrence.com minutemanpress.com
mytravelstickers.com nglantz.com nmrk.com orangetheory.com patcoproducts.com pgwautoglass.com
plattecity.org pleasanthill.com poahcommunities.com polymershapes.com postnet.com printwithme.com
regalplastic.com rentprogress.com ryancompanies.com sandlotgoods.com schuff.com sclogistics.com
screenmobile.com shelfgenie.com showmojo.com signarama.com signsbytomorrow.com smpcorp.com
smurfitwestrock.com sonnysdirect.com stoneycreekhotels.com stryten.com temperaturepro.com
tenantturner.com tenneco.com tesla.com theglassguru.com turn5.com tvh.com unilever.com
unitedhailpros.com usacanadaregion.org victaulic.com wheelpros.com wireco.com yanfeng.com zoetis.com
""".split())

# Website hosts that are not the business's own site (no domain to guess on).
PLATFORMS = set("""
business.site facebook.com instagram.com linkedin.com linktr.ee m.facebook.com sites.google.com
ueniweb.com yelp.com youtube.com
""".split())

WEBSITE_HOSTS = (
    'facebook', 'instagram', 'google', 'yelp', 'linktr', 'business.site', 'square.site', 'wixsite',
    'godaddysites', 'weebly', 'carrd.co', 'apartments.com', 'rent.com', 'zillow', 'nextdoor',
    'thumbtack', 'angi', 'homeadvisor', 'fmcsa', 'managebuilding.com', 'storageunitsoftware.com',
    'jobbersites.com', 'blogspot.', 'appfolio', 'rentcafe', 'propertyware', 'wordpress.com',
    'myshopify', 'ueniweb', 'mystrikingly', 'site123', 'webflow.io', 'netlify.app', 'vercel.app',)


# ---------------------------------------------------------------- place rules
# Roofers are Jeff's competitors.
ROOFING = re.compile(
    r'roof', re.I)

# National / corporate-owned brands by listing name (local branch does not decide on a roof).
# Known overfire: matches Ferguson Properties, a local developer (10/07).
NATIONAL = re.compile(
    r'\b(carmax|carvana|caliber|gerber collision|crash champions|service king|take 5|jiffy lube|valvoline|'
    r"discount tire|firestone|midas|meineke|pep boys|autozone|o'?reilly|advance auto|tractor supply|"
    r"home depot|lowe'?s|menards|fastenal|grainger|sherwin|u-?haul|penske|ryder|enterprise|hertz|avis|"
    r'budget truck|camping world|fedex|ups store|the ups|staples|office depot|walmart|target|costco|'
    r"sam'?s club|kroger|dillons|hy-?vee|cintas|uline|ferguson|hd supply|sunbelt rentals|united rentals|"
    r'herc rentals|ppg|coca-?cola|pepsi|frito|tyson|cargill|general mills|hostess|mars|kraft|nestle|'
    r'smithfield|bimbo|flowers foods|sysco|us foods|rush truck|freightliner of|kenworth of|peterbilt of|'
    r'mhc kenworth|murphy-hoffman|titan machinery|john deere financial|altec|snap-on|matco|cat financial|'
    r"toshiba|praxair|linde|graybar|goodyear|costa oil|flying j|pilot travel|love'?s travel|love'?s truck|"
    r'wyndham|super 8)\b', re.I)

# More brands seen in the 10/05-10/06 searches (storage, trucking, trades, glass, tires, hotels).
NATIONAL_EXTRA = re.compile(
    r'\b(public storage|extra space|cubesmart|life storage|storage ?mart|storagemart|storage sense|'
    r'securcare|simply self storage|smartstop|u-?stor-?it|go store it|j\.?\s?b\.? hunt|werner|'
    r'swift transport|knight-swift|schneider|xpo|old dominion|estes|abf freight|saia|r\+l carriers|yrc|'
    r'yellow freight|ch robinson|c\.h\. robinson|landstar|tql|total quality logistics|two men and a truck|'
    r'college hunks|allied van|north american van|mayflower|atlas van|pods|safelite|glass doctor|'
    r'big o tires|tires plus|ntb|mavis|les schwab|christian brothers automotive|take 5|valvoline|midas|'
    r'monro|aamco|cottman|maaco|one hour heating|service experts|aire serv|roto-?rooter|mr\.? rooter|'
    r'benjamin franklin plumbing|brightview|trugreen|davey tree|weed man|lawn doctor|fastsigns|signarama|'
    r'sign-?a-?rama|image360|84 lumber|builders firstsource|us lbm|abc supply|beacon building|greystar|'
    r'cortland|mid-america apartment|maa |camden|equity residential|avalonbay|hilton|marriott|holiday inn|'
    r'hampton inn|best western|la quinta|courtyard|embassy suites|petsmart|petco|banfield|vca )\b', re.I)

# Government and public-school domains and names.
GOV_DOMAIN = re.compile(
    r'(\.gov$|\.mil$|\.k12\.|k12\.org$|(^|\.)ci\.[a-z-]+\.[a-z]{2}\.us$|\.(ks|mo)\.us$|^snco\.us$|'
    r'^jocogov\.org$|^wycokck\.org$|^kcmo\.org$|^lawrenceks\.org$|^olatheks\.org$|^opkansas\.org$|'
    r'^cityofls\.net$)')

GOV_NAME = re.compile(
    r'^(city of|county of)\b|\b(animal control|police|sheriff|fire department|parks and rec|public works|'
    r'school district)\b', re.I)

# Mobile-only services have no building to roof.
MOBILE = re.compile(
    r'\bmobile\b(?! home)', re.I)

# In-home daycares run out of a house. Known overfire: "Mr " (dropped Mr LongArm, a manufacturer).
HOME_DAYCARE = re.compile(
    r'in[- ]home|home day ?care|home child ?care|child care home|family (day ?care|child ?care)|\b(mrs?|'
    r"ms|miss)\.?\s|'s (day ?care|child ?care)(?!.*\b(center|academy|preschool)\b)", re.I)

# 10/06 rule: home-service trades (0 human replies from ~130) are dropped even with an address.
HOME_SERVICE = re.compile(
    r'lawn|landscap|tree service|arborist|plumb|hvac|heating|air condition|mechanical contractor|moving|'
    r'mover|painter|painting|pest control|exterminator|remodel|home builder|general contractor|'
    r'construction company|concrete contractor|handyman|carpet clean|cleaning service|janitorial|'
    r'pressure washing|gutter|fence contractor|electrician|pool cleaning|septic|chimney|window cleaning|'
    r'deck builder|siding', re.I)

# 10/06 rule: office-suite tenants and small medical, dental and salon practices.
TENANT = re.compile(
    r'insurance|accountant|\bcpa\b|tax prep|title company|software|marketing|consultant|staffing|'
    r'employment agency|real estate agent|realtor|real estate agency|attorney|lawyer|law firm|financial|'
    r'dentist|dental|orthodont|chiropract|physical therapist|medical clinic|doctor|physician|optometrist|'
    r'beauty salon|hair salon|nail salon|barber|spa\b|massage', re.I)

# Property managers count even with a PO box or a suite: they manage other buildings.
PROPERTY = re.compile(
    r'property management|apartment|real estate developer|condominium', re.I)

# Small roofs or tenants with 0 interested replies so far (jeff-positive-reply-patterns).
SMALL_ROOF = re.compile(
    r'gym|fitness|yoga|pilates|martial arts|personal trainer|crossfit|day care|daycare|child care|'
    r'preschool|kindergarten|tutoring|salon|barber|nail|tattoo|boutique|gift shop|florist|coffee|cafe|'
    r'restaurant|bakery|food truck|liquor store|vape|smoke shop|cell phone|thrift|consignment|pawn|'
    r'dry clean|laundromat|car wash|storage unit|electronics vending|atm|kiosk|food pantry|'
    r'donations center|indoor golf|golf simulator|indoor playground|trampoline|escape room|glass & mirror|'
    r'rehabilitation center', re.I)

# A suite / unit / floor in the address means a tenant in someone else's building (fixed 10/09:
# '#101', unit letters like '6602 Royal St A' and '6600 A Royal St', '5th floor').
RENTER_ADDR = re.compile(
    r'\b(suite|ste\.?|unit|apt\.?|space|bay)\s*[a-z0-9-]+|#\s*[a-z0-9-]+|\b\d+(st|nd|rd|th)\s+floor\b|'
    r'\bfloor\s+\d+|^\d+\s+[a-df-mo-rt-vx-z]\s|\b(st|dr|rd|ave|blvd|ln|pkwy|ct|cir|way|ter|'
    r'pl)\.?\s+[a-df-mo-rt-vx-z](?=,)', re.I)


# ---------------------------------------------------------------- email rules
# Personal and ISP inboxes are never kept (cold-email-no-personal-inboxes).
PERSONAL = re.compile(
    r'@(gmail|googlemail|yahoo|ymail|hotmail|outlook|live|msn|aol|icloud|me|mac|proton|protonmail|comcast|'
    r'att|sbcglobal|verizon|bellsouth|charter|cox|earthlink|kc\.rr|twc|everestkc|embarqmail|centurylink)\.', re.I)

PERSONAL_EXTRA = re.compile(
    r'@(rocketmail|mail|gmx|zoho|aim|juno|netzero|windstream|frontier|suddenlink|mediacombb|sbc|prodigy|q|'
    r'wowway|rr)\.', re.I)

# Junk addresses scraped from site code: placeholders, no-reply, font and builder credits.
JUNK_LOCAL = re.compile(
    r'^(privacy\w*|noreply|no-reply|donotreply|careers|jobs|hr|recruit\w*|press|media|legal|abuse|'
    r'investor\w*|webmaster|example|test|your|email|name|user|support@wix)', re.I)

JUNK_DOMAIN = re.compile(
    r'@(automattic|latofonts|micahrich|wixpress|sentry|example|godaddy|squarespace|wix|domain|email|'
    r'yourdomain|sentry-next|mysite)\.', re.I)

# Junk role inboxes (backfill build.py JUNK_ROLE + backfill review.py JUNK_LOCAL).
JUNK_ROLE = re.compile(
    r'(?:^(careers?|jobs?|hr|humanresources|recruit\w*|talent|press|pr|media\w*|webmaster|donations?|'
    r'donate|ir|investors?|\w*claims|collections|helpdesk|privacy|legal|warranty|accounting\w*|invoic\w*|'
    r'billing|ap|ar|payables|marketing\w*)$)|(?:^(\d.*|smallgroups|social|finance|membership|institute|'
    r'communications|websiteemail|website|web|efiles|compliance|helpline|websamples|driverrecruit\w*|'
    r'\w*media|employment|books|ecommservice)$)', re.I)

# Inboxes on a platform, agency or government domain (JeffLeads 10/11 verify.py).
PLATFORM_INBOX = re.compile(
    r'wix|frontend|squarespace|godaddy|weebly|wordpress|sentry|example\.|domain\.com|email\.com|'
    r'yourdomain|istudiosg|churchtrac|shulcloud|showmojo|appfolio|rentcafe|\.gov$|\.mil$|k12\.|'
    r'schools\.org|usd\d+|sitelink|mfs-ent', re.I)


# ---------------------------------------------------------------- tags, grouping, guessing
# Business types with 0 interested replies so far: tagged B on the review sheet, not dropped.
TIER_B = re.compile(
    r'school|educational|academy|preschool|nursing|assisted|senior|retirement|care home|memory care|'
    r'funeral|cemetery|cremat|hospital|event venue|banquet|wedding|winery|brewery|brewpub|distillery|'
    r'hotel|motel|inn$|detailing|soccer|sports club|golf|country club|camp\b|museum|theater|pumpkin|'
    r'orchard|pet groom', re.I)

# Churches go to the Churches campaign, everything else to 8/20.
CHURCH = re.compile(
    r'church|chapel|parish|worship|religious|ministr|temple|synagogue|mosque|islamic|jewish|congregation|'
    r'cathedral|fellowship|chabad', re.I)

# Best-replying categories are guessed first, so a credit stop leaves the weakest untried.
GUESS_PRIORITY = re.compile(
    r'church|apartment|property management|townhouse|dealer|body shop|collision|manufactur|printer|'
    r'warehouse|trucking|storage|funeral|venue|shelter|developer|disability|rental|veterinar|'
    r'animal hospital|truck repair', re.I)

# Owner-occupied types the export filter never searched for (JeffLeads 10/11 status.py). Reference only:
# owner_run() is the rule in force since 10/15.
SALVAGE = re.compile(
    r'automation company|pharmaceutical company|aerospace company|railroad company|grain elevator|^farm$|'
    r'restaurant supply|landscaping supply|countertop|tool store|lighting store|newspaper publisher|'
    r'aircraft maintenance|flight school|business to business|e-commerce service|leasing service|'
    r'parking garage|retreat center|association / organization|corporate office|furniture store|'
    r'flooring store|carpet store|tile store|appliance store|hardware store|home improvement store|'
    r'garden center|plant nursery|sporting goods store|music store|gun shop|shooting range|'
    r'auto parts store|grocery store|^bank$|credit union|financial institution|feed store|'
    r'farm equipment supplier|agricultural|equipment rental|steel distributor|metal supplier|pallet|'
    r'forklift|material handling|electric motor|meat processor|meat packer|butcher|distribution service|'
    r'logistics service|business park|industrial', re.I)

# ---------------------------------------------------------------- owner-run rule (2026-10-15)
NOT_OWNER_SHOP = re.compile(
    # offices and professional services
    r"designer|design agency|video production|film production|media company|advertising|marketing|"
    r"public relations|graphic|photograph|portrait studio|architect|engineer|surveyor|inspector|appraiser|"
    r"legal|lawyer|attorney|divorce|notary|escrow|loan|mortgage|finance broker|money transfer|"
    r"private equity|holding company|business broker|business develop|business administration|"
    r"business networking|business related|business to business service|professional services|"
    r"professional organizer|consult|recruit|temp agency|employment|staffing|call center|coworking|"
    r"^office$|^company$|corporate campus|information services|computer support|computer service|"
    r"computer security|computer networking|web hosting|database|internet service|telecommunications|"
    r"market researcher|meeting planning|travel agency|travel lounge|real estate|loss adjuster|"
    r"energy advisory|news service|direct mail|tax |human resource|"
    # contractors, home trades, mobile services
    r"contractor|construction|restoration service|installation|installer|repair service|"
    r"carpenter|masonry|glazier|locksmith|junk removal|snow removal|dumpster|line marking|"
    r"interior plant|cleaners|security service|security guard|fire protection|elevator service|"
    r"antenna service|asbestos|soil testing|environmental health|drone service|crane service|"
    r"well drilling|drilling|pond|swimming pool repair|shed builder|golf course builder|forestry|"
    r"caterer|catering|dj service|photo booth|wedding service|entertainment agency|limousine|chauffeur|"
    r"airport shuttle|bus charter|courier|delivery|shipping|vehicle shipping|transportation service|"
    r"dog trainer|pet trainer|pet care|cat breeder|dog breeder|artist$|skating instructor|scuba|"
    r"home help|home health|nursing agency|foster care|adoption|"
    # medical, therapy, social services, nonprofits
    r"clinic|therapist|therapy|psycholog|psychiatr|counselor|mental health|medical|hospital|"
    r"pediatric|audiologist|optician|eye care|ophthalm|radiolog|urgent care|birth center|"
    r"pregnancy|weight loss|wellness|lymph|iv therapy|laser hair|skin care|permanent make-up|"
    r"health center|blood donation|occupational health|support group|deaf service|halfway house|"
    r"group home|social service|non-profit|charity|foundation|volunteer|association|chamber of commerce|"
    r"labor union|economic development|environmental organization|arts organization|club$|"
    r"sports association|mission$|seminary|monastery|"
    # government, utilities, public venues, schools
    r"utility|gas company|department of motor|driver's license|license bureau|social security|"
    r"tax assessor|courthouse|housing authority|rescue squad|park$|^garden$|nature preserve|playground|"
    r"museum|historical|landmark|tourist attraction|religious destination|stadium|arena|amphitheater|"
    r"fairground|convention center|festival|public swimming|aquatic center|athletic field|soccer field|"
    r"soccer practice|pickleball court|beach volleyball|public golf|school|university|college|"
    r"education|learning center|training center|emergency training|academy|classes|"
    # no building of their own
    r"housing development|gated community|^house$|housing association|vacation home|cabin rental|"
    r"short term apartment|communications tower|parking lot|electric vehicle charging|mailbox rental|"
    r"festival|airline|chapel$|gurudwara|hindu temple|pottery classes|"
    r"rental agency$|appliance rental|car rental|"
    # second look: tenants, home trades or corporate/public operators despite a shop-like name
    r"pet groomer|solar energy|refinishing|garbage collection|wildlife rescue|hearing aid|"
    r"mobile phone repair|clothing alteration|key duplication|internet shop|food court|food broker|"
    r"helicopter tour|estate liquidator|dance company|children's camp|auditorium|^aquarium$|casino|"
    r"fixed-base operator|television studio|performing arts|ballet|concert hall|art center|"
    r"alternative medicine|cultural center|veterans organization|shopping mall|home automation", re.I)
# owner-run even though a word above matches
OWNER_EXCEPTIONS = re.compile(r"musical instrument repair|bicycle repair|electronics repair shop|"
                              r"small engine repair|air compressor repair|refrigerator repair|"
                              r"golf club|tennis club|swim club|ice hockey club|board game club|"
                              r"sauna club|comedy club|crane rental|scaffolding rental|"
                              r"musical instrument rental", re.I)

# Listing names that need a hand fix before upload (JeffLeads 10/11 build_upload.py).
NAME_FIX = {'Refreshments': 'KC Refreshments', 'All Tile - Carpet Cushions & Supplies': 'Carpet Cushions & Supplies', 'Truman Heritage Habitat for Humanity Independence ReStore': 'the Habitat ReStore', '87 PIT STOP Powder Coating and Restorations': '87 Pit Stop', 'KC Wholesale - Exit 28 Service Center': 'KC Wholesale', 'Westside Family Church Leavenworth': 'Westside Family Church', 'Chabad House Center of Kansas City': 'Chabad House', 'St Paul Lutheran Church & School': 'St. Paul Lutheran Church', 'K C Machine': 'KC Machine', 'BURNETT AUTOMOTIVE INC': 'Burnett Automotive', 'Craig A. Kindiger, MS': 'Restart', 'Hammerspace Community Workshop & Makerspace': 'Hammerspace', 'Claycomo Shooters Indoor Range & Gun Store': 'Claycomo Shooters', 'Church of Christ-Temple Lot': 'Church of Christ (Temple Lot)'}

# Generic-inbox prefixes by category, tried in order; the first Reoon safe / role_account wins.
GUESS_PREFIXES = [  # (category regex, prefixes)
    (r'church|chapel|parish|worship|religious|ministr|temple|synagogue|mosque', ['office', 'info', 'church', 'admin', 'contact', 'pastor']),
    (r'apartment|townhouse|condominium|property management|rental agency|retirement|senior', ['leasing', 'office', 'info', 'manager', 'contact', 'admin']),
    (r'dealer|auto|car |tire|towing|collision|body shop|detailing|repair', ['info', 'service', 'sales', 'office', 'contact', 'admin']),
    (r'venue|winery|brewery|hotel|event', ['info', 'events', 'office', 'contact', 'manager', 'admin']),
    (r'funeral|cemetery|cremation', ['info', 'office', 'contact', 'admin', 'funeralhome', 'manager']),
    (r'.*', ['info', 'office', 'sales', 'contact', 'admin', 'orders']),
]

SAFE = {"safe", "role_account"}  # the only Reoon results kept, and never when is_catch_all


# ---------------------------------------------------------------- helpers
def host_of(url):
    return re.sub(r"^https?://", "", (url or "").strip().lower()).split("/")[0].split("?")[0]


def mail_domain(host):
    """Mail lives on the registrable domain, not on site subdomains."""
    return ".".join(host.split(".")[-2:])


def root_label(d):
    parts = d.split(".")
    return parts[-2] if len(parts) >= 2 else d


def norm_city(c):
    c = (c or "").lower().replace("'", "").replace(".", "").strip()
    return re.sub(r"\s+", " ", c)


def city_of(p):
    """Maps city, or the city parsed from the address when the city field is blank."""
    if p.get("city"):
        return norm_city(p["city"])
    m = re.search(r",\s*([^,]+?),\s*(?:KS|MO|Kansas|Missouri)", p.get("address") or "")
    return norm_city(m.group(1)) if m else ""


def site_domain(website):
    """The business's own mail domain from its website, or None for platform pages and no website."""
    d = host_of(website).removeprefix("www.")
    if not d or d in PLATFORMS or any(x in d for x in WEBSITE_HOSTS):
        return None
    return mail_domain(d)


def is_church(text):
    return bool(CHURCH.search(text or ""))


def group_of(category, name):
    return "church" if is_church(f"{category} {name}") else "8/20"


def accepted(res):
    """A Reoon answer we keep: safe or role_account, and not on a catch-all domain."""
    return bool(res) and res.get("status") in SAFE and not res.get("is_catch_all")


def reoon_label(res):
    st = (res or {}).get("status") or "error"
    if (res or {}).get("is_catch_all") and st != "catch_all":
        st += " (catch-all)"
    return st


# ---------------------------------------------------------------- place and email rules
def place_reason(p, dom, known):
    """Why a place can't be a lead (clean_run17.place_reason), or None. `known` = taken mail domains."""
    name, cat = p.get("name") or "", p.get("category") or ""
    if ROOFING.search(cat) or ROOFING.search(name) or (dom and "roof" in dom):
        return "roofing competitor"
    if (dom and GOV_DOMAIN.search(dom)) or GOV_NAME.search(name) or re.search(
            r"government|city hall|police|fire station|post office|library|public school|high school|"
            r"school district", cat, re.I):
        return "government / public school"
    if NATIONAL.search(name) or NATIONAL_EXTRA.search(name):
        return "national chain (name)"
    if dom and (root_label(dom) in CHAINS or dom in CHAIN_DOMAINS or dom in REVIEW_NATIONAL):
        return "national chain (domain)"
    if MOBILE.search(name):
        return "mobile-only (no building)"
    if HOME_DAYCARE.search(name):
        return "in-home daycare"
    if HOME_SERVICE.search(cat):
        return "home-service trade"
    if TENANT.search(cat):
        return "office / medical tenant"
    if not (p.get("address") or "").strip() and not PROPERTY.search(cat):
        return "no Google address (home-based / no building)"
    if city_of(p) not in AREA or (p.get("state") or "").lower() not in STATES:
        return "out of area"
    if dom and dom in known:
        return "domain already in PlusVibe / delivered"
    return None


def reason(p, dom, known):
    """place_reason plus the 10/08-10/09 small-roof and renter rules (clean_batch2.reason)."""
    why = place_reason(p, dom, known)
    if why:
        return why
    cat = p.get("category") or ""
    if SMALL_ROOF.search(cat):
        return "small roof / tenant type"
    if RENTER_ADDR.search(p.get("address") or "") and not PROPERTY.search(cat):
        return "renting (suite/unit address)"
    pe = (p.get("primary_email") or "").lower()
    if (dom and SCHOOL_GOV.search(dom)) or ("@" in pe and SCHOOL_GOV.search(pe.split("@")[1])):
        return "government / public school"
    return None


# Added 2026-10-15 (pipeline replay): Kansas school districts (usd497.org) and places whose inbox is on a
# .gov / .mil / k12 domain are public bodies. Before, their email was only skipped and they went to guessing.
SCHOOL_GOV = re.compile(r"^usd\d+\.|(^|\.)k12\.|\.gov$|\.mil$")


def bad_email(e):
    """Personal / ISP, junk or junk-role address."""
    return bool(PERSONAL.search(e) or PERSONAL_EXTRA.search(e) or JUNK_LOCAL.search(e) or JUNK_DOMAIN.search(e)
                or JUNK_ROLE.match(e.split("@")[0]))


def own_email(p, dom):
    """First good email on the business's own domain (clean_run17.own_email). p["all_emails"] is '; '-joined."""
    for e in [p.get("primary_email") or ""] + (p.get("all_emails") or "").split("; "):
        e = e.strip().lower().rstrip(".")
        if "@" not in e or bad_email(e):
            continue
        edom = e.split("@", 1)[1]
        if edom.startswith("www.") or edom in REVIEW_NATIONAL:
            continue
        if mail_domain(edom) == dom:
            return e
    return None


def pick_email(p, dom):
    """own_email, else the primary email when it isn't bad (clean_batch2.pick_email), never a platform,
    agency or government inbox. None means: guess on the website domain instead."""
    email = own_email(p, dom) if dom else None
    if not email:
        e = (p.get("primary_email") or "").strip().lower()
        email = e if "@" in e and not bad_email(e) else None
    if email and PLATFORM_INBOX.search(email.split("@")[1]):
        return None
    return email


def owner_run(cat):
    """2026-10-15 rule: an off-target business is worth emailing when it's an owner-run shop."""
    cat = cat or ""
    if not cat:
        return False
    return bool(OWNER_EXCEPTIONS.search(cat)) or not NOT_OWNER_SHOP.search(cat)


def guess_prefixes(cat):
    return next(p for rx, p in GUESS_PREFIXES if re.search(rx, cat or "", re.I))


def clean_company(name):
    """Company name for the {{company_name}} merge field (JeffLeads 10/11 clean_name)."""
    name = NAME_FIX.get(name.strip(), name.strip())
    name = re.sub(r"\s*[|].*$", "", name)
    # "Acme Storage - Olathe" -> "Acme Storage" (a location suffix reads oddly in the merge field)
    m = re.match(r"^(.*\S)\s+[-–—]\s+([^-–—]+)$", name)
    if m and norm_city(m.group(2)) in AREA:
        name = m.group(1)
    name = re.sub(r",?\s+(Inc\.?|LLC|L\.L\.C\.?|Corp\.?|Corporation)$", "", name, flags=re.I)
    name = re.sub(r",?\s+(Inc\.?|LLC)$", "", name, flags=re.I)
    return name.strip(" ,")
