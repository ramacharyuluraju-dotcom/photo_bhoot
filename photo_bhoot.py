import streamlit as st
import pandas as pd
from PIL import Image, ImageDraw, ImageFont
import io
import os
import re
import urllib.request
import zipfile
import barcode
from barcode.writer import ImageWriter
from datetime import datetime
from supabase import create_client, Client

st.set_page_config(page_title="AMCEC Unified Student Portal", page_icon="🎓", layout="wide")

# ==========================================
# 1. SETUP & SUPABASE CONNECTION
# ==========================================
ADMIN_USER = str(st.secrets.get("admin", {}).get("username", "AMC_COE_ADMIN"))
ADMIN_PIN = str(st.secrets.get("admin", {}).get("pin", "9999"))

@st.cache_resource
def init_connection():
    try:
        url = st.secrets["supabase"]["url"]
        key = st.secrets["supabase"]["key"]
        return create_client(url, key)
    except Exception:
        return None

supabase = init_connection()

if not supabase:
    st.warning("⚠️ Database connection failed. Check your Supabase secrets in .streamlit/secrets.toml")

# --- INITIALIZE SESSION STATES ---
if 'student_auth' not in st.session_state:
    st.session_state.student_auth = False
    st.session_state.is_admin = False
    st.session_state.student_usn = ""
    st.session_state.student_name = ""
    st.session_state.upload_count = 0

# ==========================================
# 2. HELPER FUNCTIONS
# ==========================================
@st.cache_data
def get_college_logo():
    if supabase:
        try:
            res = supabase.storage.from_("College_Logos").download("College_logo.png")
            return res
        except: pass
    return None

def fetch_student_photo(usn):
    if not supabase: return None
    exact_usn = str(usn).strip().upper()
    
    for ext in ['.jpg', '.JPG', '.png', '.jpeg']:
        try:
            res = supabase.storage.from_("StakeHolders_Photos").download(f"{exact_usn}{ext}")
            if res and len(res) > 0: 
                return res
        except Exception:
            continue
    return None

def extract_branch(usn):
    match = re.search(r'\d{2}([A-Z]{2,3})\d{2,3}', str(usn).upper())
    return match.group(1) if match else "GEN"

# ==========================================
# 3. ID CARD GENERATOR ENGINE
# ==========================================
@st.cache_data
def download_cloud_font():
    """Downloads the font once and saves it locally to avoid caching C-pointers."""
    font_path = "Roboto-Bold.ttf"
    if not os.path.exists(font_path):
        try:
            url = "https://github.com/googlefonts/roboto/raw/main/src/hinted/Roboto-Bold.ttf"
            req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
            with open(font_path, "wb") as f:
                f.write(urllib.request.urlopen(req).read())
        except Exception:
            return None
    return font_path

def get_cloud_font(size):
    """Loads font from the downloaded file."""
    try:
        return ImageFont.truetype("arial.ttf", size)
    except IOError:
        font_path = download_cloud_font()
        if font_path:
            try:
                return ImageFont.truetype(font_path, size)
            except Exception:
                pass
        return ImageFont.load_default()

def generate_id_card(name, usn, sem, logo_bytes=None, photo_bytes=None):
    card_width, card_height = 600, 850
    card = Image.new('RGB', (card_width, card_height), color='#19233A')
    draw = ImageDraw.Draw(card)

    # Base Layout
    draw.rectangle([50, 50, 420, 550], fill='#B0B0B0')  
    draw.rectangle([420, 50, 550, 550], fill='#D9534F') 

    # Profile Photo
    if photo_bytes:
        try:
            photo = Image.open(io.BytesIO(photo_bytes)).convert('RGB')
            photo = photo.resize((370, 500), Image.Resampling.LANCZOS)
            card.paste(photo, (50, 50))
        except Exception: pass

    # College Logo
    if logo_bytes:
        try:
            logo = Image.open(io.BytesIO(logo_bytes)).convert('RGBA')
            logo.thumbnail((110, 110), Image.Resampling.LANCZOS)
            logo_x = 420 + (130 - logo.width) // 2
            card.paste(logo, (logo_x, 60), mask=logo)
        except Exception: pass

    # Vertical College Name - Font size reduced to prevent overlap
    font_college = get_cloud_font(26)
    college_text = "AMC ENGINEERING COLLEGE"
    try:
        text_bbox = draw.textbbox((0,0), college_text, font=font_college)
        tw, th = text_bbox[2] - text_bbox[0], text_bbox[3] - text_bbox[1]
        txt_img = Image.new('RGBA', (tw + 10, th + 10), (255, 255, 255, 0))
        ImageDraw.Draw(txt_img).text((0, 0), college_text, font=font_college, fill='white')
        
        rotated_txt = txt_img.rotate(270, expand=True)
        rt_w, rt_h = rotated_txt.size
        txt_x = 420 + (130 - rt_w) // 2
        card.paste(rotated_txt, (txt_x, 190), mask=rotated_txt)
    except Exception: pass

    # Teal Banner
    draw.rectangle([50, 460, 550, 600], fill='#17A2B8')
    
    font_title = get_cloud_font(42)  
    font_sub = get_cloud_font(26)    
    
    display_name = str(name).upper()[:19] 
    draw.text((70, 470), display_name, font=font_title, fill='white')
    # Removed DEPT from the banner string
    draw.text((70, 545), f"ID: {str(usn).upper()}  |  SEM: {sem}", font=font_sub, fill='white')

    # Barcode
    if usn:
        try:
            rv = io.BytesIO()
            code128 = barcode.get('code128', str(usn).strip().upper(), writer=ImageWriter())
            code128.write(rv, options={"write_text": False, "module_height": 13.0, "quiet_zone": 1.5})
            rv.seek(0)
            bc_img = Image.open(rv).convert('RGB')
            bc_img = bc_img.resize((500, 130), Image.Resampling.LANCZOS)
            card.paste(bc_img, (50, 620))
        except Exception: pass

    # Footer
    font_footer = get_cloud_font(20)
    footer_text = "www.amcgroup.edu.in"
    try:
        text_bbox = draw.textbbox((0, 0), footer_text, font=font_footer)
        text_x = (card_width - (text_bbox[2] - text_bbox[0])) // 2
    except: text_x = 200 
    draw.text((text_x, 790), footer_text, font=font_footer, fill='white')

    return card

def create_a4_pages(cards):
    """3 Columns x 4 Rows (12 Cards per Page) for 300DPI A4"""
    A4_WIDTH, A4_HEIGHT = 2480, 3508
    pages = []
    
    x_offsets = [200, 940, 1680] 
    y_offsets = [40, 900, 1760, 2620] 
    
    for i in range(0, len(cards), 12):
        chunk = cards[i:i+12]
        a4 = Image.new('RGB', (A4_WIDTH, A4_HEIGHT), 'white')
        for idx, card in enumerate(chunk):
            col = idx % 3
            row = idx // 3
            a4.paste(card, (x_offsets[col], y_offsets[row]))
        pages.append(a4)
    return pages

# ==========================================
# 4. MAIN NAVIGATION & UI ROUTING
# ==========================================
mode = st.sidebar.radio("Navigation", [
    "📸 Student Photo Booth", 
    "👑 AMC_COE_ADMIN Console"
])

# ------------------------------------------
# MODE 1: STUDENT PHOTO BOOTH
# ------------------------------------------
if mode == "📸 Student Photo Booth":
    st.title("📸 AMCEC Official Photo Portal")
    st.markdown("Upload your formal passport-size photograph for your Academic Records and ID Cards.")

    if not st.session_state.student_auth:
        st.info("🔒 Please verify your identity to proceed.")
        with st.form("auth_form"):
            usn_input = st.text_input("User Name (USN / Admission No.)").strip().upper()
            pin_input = st.text_input("4-Digit PIN", type="password").strip()
            submitted = st.form_submit_button("Verify Identity", type="primary", use_container_width=True)
            
            if submitted:
                if not usn_input or not pin_input:
                    st.error("⚠️ Both fields are required.")
                else:
                    with st.spinner("Verifying records..."):
                        res = supabase.table("master_students").select("usn, admission_number, full_name, photo_pin, photo_upload_count").eq("usn", usn_input).execute()
                        if not res.data:
                            res = supabase.table("master_students").select("usn, admission_number, full_name, photo_pin, photo_upload_count").eq("admission_number", usn_input).execute()
                        
                        if not res.data:
                            st.error("❌ User Name not found in the master database.")
                        else:
                            student_record = res.data[0]
                            db_pin = str(student_record.get('photo_pin', '')).strip()
                            
                            if db_pin and pin_input == db_pin:
                                st.session_state.student_auth = True
                                st.session_state.student_usn = student_record.get('usn') if student_record.get('usn') else student_record.get('admission_number')
                                st.session_state.student_name = student_record['full_name']
                                st.session_state.upload_count = int(student_record.get('photo_upload_count') or 0)
                                st.rerun()
                            else:
                                st.error("❌ Incorrect PIN.")
    else:
        st.success(f"✅ Welcome, **{st.session_state.student_name}** (`{st.session_state.student_usn}`)")
        if st.button("🚪 Logout"):
            st.session_state.student_auth = False
            st.session_state.student_usn = ""
            st.rerun()
            
        st.markdown("---")
        if st.session_state.upload_count > 0:
            st.info(f"🔄 You have already uploaded a photo. Uploading a new one will replace your existing formal photo. (Uploads so far: {st.session_state.upload_count})")
            
        input_method = st.radio("Choose Photo Source:", ["Upload a File", "Use Web Camera"], horizontal=True)
        uploaded_file = st.file_uploader("Upload an image (JPG/PNG)", type=['jpg', 'jpeg', 'png']) if input_method == "Upload a File" else st.camera_input("Take a picture")
        
        if uploaded_file is not None:
            if uploaded_file.size > 5 * 1024 * 1024:
                st.error("❌ File Too Large! Please compress the image to under 5 MB.")
            else:
                try:
                    img = Image.open(uploaded_file)
                    if img.mode != 'RGB': img = img.convert('RGB')
                    
                    st.markdown("### 👀 Review & Submit")
                    col1, col2 = st.columns([1, 2])
                    with col1: st.image(img, use_container_width=True)
                    with col2:
                        st.warning("Make sure your face is clearly visible, well-lit, and directly facing the camera.")
                        if st.checkbox("I confirm this photo meets college guidelines."):
                            if st.button("☁️ Confirm & Upload to Database", type="primary", use_container_width=True):
                                with st.spinner("Uploading..."):
                                    img_byte_arr = io.BytesIO()
                                    img.save(img_byte_arr, format='JPEG', quality=85, optimize=True)
                                    final_image_bytes = img_byte_arr.getvalue()
                                    file_name = f"{st.session_state.student_usn}.jpg"
                                    
                                    try:
                                        supabase.storage.from_("StakeHolders_Photos").upload(file=final_image_bytes, path=file_name, file_options={"content-type": "image/jpeg", "upsert": "true"})
                                    except Exception:
                                        supabase.storage.from_("StakeHolders_Photos").update(file=final_image_bytes, path=file_name, file_options={"content-type": "image/jpeg"})
                                    
                                    new_count = st.session_state.upload_count + 1
                                    supabase.table("master_students").update({"photo_upload_count": new_count, "last_photo_upload": datetime.now().isoformat()}).eq("usn", st.session_state.student_usn).execute()
                                    st.session_state.upload_count = new_count
                                    st.success("🎉 Success! Your photo has been officially updated.")
                                    st.balloons()
                except Exception as e: st.error(f"Error processing image: {e}")

# ------------------------------------------
# MODE 2: AMC_COE_ADMIN CONSOLE
# ------------------------------------------
elif mode == "👑 AMC_COE_ADMIN Console":
    st.title("👑 AMC_COE_ADMIN Unified Console")
    
    if not st.session_state.is_admin:
        with st.form("admin_login"):
            username = st.text_input("Admin ID").strip()
            password = st.text_input("Password", type="password").strip()
            if st.form_submit_button("Login"):
                if username == ADMIN_USER and password == ADMIN_PIN:
                    st.session_state.is_admin = True
                    st.rerun()
                else:
                    st.error("Invalid Credentials")
    else:
        st.success(f"✅ Logged in as {ADMIN_USER}")
        if st.button("Logout"):
            st.session_state.is_admin = False
            st.rerun()
            
        tab1, tab2, tab3 = st.tabs(["📊 Photo Upload Analytics", "🪪 Single Temp ID Gen", "🖨️ Bulk Temp ID Print Engine"])
        
        # --- TAB 1: PHOTO ANALYTICS ---
        with tab1:
            st.subheader("Live Database Metrics")
            with st.spinner("Fetching data..."):
                all_data = []
                start = 0; step = 1000
                while True:
                    res = supabase.table("master_students").select("usn, full_name, branch_code, photo_upload_count, last_photo_upload, scheme_batch").range(start, start + step - 1).execute()
                    if not res.data: break
                    all_data.extend(res.data)
                    if len(res.data) < step: break
                    start += step
                    
                df = pd.DataFrame(all_data)
                
                if not df.empty:
                    df['photo_upload_count'] = df['photo_upload_count'].fillna(0).astype(int)
                    total_students = len(df)
                    total_uploaded = len(df[df['photo_upload_count'] > 0])
                    total_pending = total_students - total_uploaded
                    completion_rate = (total_uploaded / total_students) * 100 if total_students > 0 else 0
                    
                    col1, col2, col3, col4 = st.columns(4)
                    col1.metric("Total Students", total_students)
                    col2.metric("Photos Uploaded", total_uploaded)
                    col3.metric("Pending Uploads", total_pending)
                    col4.metric("Completion Rate", f"{completion_rate:.1f}%")
                    
                    st.divider()
                    
                    st.markdown("**Recent Upload Activity**")
                    uploaded_df = df[df['photo_upload_count'] > 0].sort_values(by="last_photo_upload", ascending=False).head(100)
                    st.dataframe(uploaded_df[['usn', 'full_name', 'branch_code', 'photo_upload_count', 'last_photo_upload']], use_container_width=True, hide_index=True)
                    
                    st.markdown("**Pending Uploads (Filter by Batch)**")
                    if 'scheme_batch' in df.columns:
                        df['scheme_batch'] = pd.to_numeric(df['scheme_batch'], errors='coerce').fillna(0).astype(int)
                        available_batches = sorted(df[df['scheme_batch'] > 0]['scheme_batch'].unique().tolist(), reverse=True)
                        if available_batches:
                            selected_batch = st.selectbox("Batch (e.g., 26 for 2026):", available_batches)
                            pending_df = df[(df['photo_upload_count'] == 0) & (df['scheme_batch'] == selected_batch)]
                            st.dataframe(pending_df[['usn', 'full_name', 'branch_code']], use_container_width=True, hide_index=True)
                else:
                    st.warning("No student records found.")

        # --- TAB 2: SINGLE TEMP ID GEN ---
        with tab2:
            st.subheader("🪪 Individual Temp ID Generator")
            c1, c2 = st.columns(2)
            
            with c1:
                with st.form("single_form"):
                    name = st.text_input("Full Name")
                    usn = st.text_input("USN / Temp ID").strip().upper()
                    sem = st.number_input("Semester", 1, 10, 1)
                    # Removed manual branch input to keep the form clean
                    photo_file = st.file_uploader("Override Photo (Leave empty to fetch from DB)", type=['jpg', 'jpeg', 'png'])
                    submit = st.form_submit_button("Generate Card", type="primary")
                    
            with c2:
                if submit and name and usn:
                    with st.spinner("Generating..."):
                        photo_bytes = photo_file.read() if photo_file else fetch_student_photo(usn)
                        logo_bytes = get_college_logo()
                        
                        card = generate_id_card(name, usn, sem, logo_bytes, photo_bytes)
                        st.image(card, width=350)
                        
                        buf = io.BytesIO()
                        card.save(buf, format="PNG")
                        st.download_button("⬇️ Download PNG", data=buf.getvalue(), file_name=f"ID_{usn}.png", mime="image/png")

        # --- TAB 3: BULK TEMP ID ENGINE ---
        with tab3:
            st.subheader("Bulk Branch-Wise Print Engine (A4 3x4 Grid)")
            st.info("Upload a CSV containing `usn`, `full_name`, and `current_sem`. The system automatically fetches photos from Supabase, groups students by branch, and generates ready-to-print A4 PDF sheets.")
            
            csv_file = st.file_uploader("Upload Master CSV", type=['csv'])
            if csv_file and st.button("🚀 Execute Bulk Print Generation", type="primary"):
                df_print = pd.read_csv(csv_file)
                df_print.columns = [c.strip().lower() for c in df_print.columns]
                
                if not all(col in df_print.columns for col in ['usn', 'full_name', 'current_sem']):
                    st.error("CSV missing required columns: usn, full_name, current_sem")
                else:
                    if 'branch' not in df_print.columns:
                        df_print['branch'] = df_print['usn'].apply(extract_branch)
                        
                    logo_bytes = get_college_logo()
                    
                    zip_buffer = io.BytesIO()
                    progress_bar = st.progress(0)
                    status_text = st.empty()
                    total_branches = len(df_print['branch'].unique())
                    
                    with zipfile.ZipFile(zip_buffer, "w", zipfile.ZIP_DEFLATED) as zf:
                        for b_idx, (branch, group) in enumerate(df_print.groupby('branch')):
                            status_text.text(f"Processing Branch: {branch} ({len(group)} students)...")
                            
                            cards = []
                            for _, row in group.iterrows():
                                photo_bytes = fetch_student_photo(row['usn'])
                                card = generate_id_card(row['full_name'], row['usn'], row['current_sem'], logo_bytes, photo_bytes)
                                cards.append(card)
                                
                            a4_pages = create_a4_pages(cards)
                            
                            if a4_pages:
                                pdf_buf = io.BytesIO()
                                # Resolution=300 forces the PDF bounds to match real A4 size exactly
                                a4_pages[0].save(pdf_buf, format='PDF', save_all=True, append_images=a4_pages[1:], resolution=300)
                                zf.writestr(f"Temp_ID_Cards_{branch}.pdf", pdf_buf.getvalue())
                                
                            progress_bar.progress((b_idx + 1) / total_branches)
                    
                    status_text.success("✅ All Branch PDFs generated and packaged successfully!")
                    st.download_button(
                        label="📥 Download Class-Teacher Print Bundles (ZIP)",
                        data=zip_buffer.getvalue(),
                        file_name=f"AMC_Temp_IDs_{datetime.now().strftime('%Y%m%d')}.zip",
                        mime="application/zip",
                        type="primary",
                        use_container_width=True
                    )
