import streamlit as st
import io
import re
from PIL import Image, ImageOps
from supabase import create_client, Client

# ==========================================
# 1. SETUP & CONFIGURATION
# ==========================================
st.set_page_config(page_title="Student Photo Portal", page_icon="📸", layout="centered")

@st.cache_resource
def init_connection():
    url = st.secrets.get("supabase", {}).get("url", "YOUR_SUPABASE_URL")
    key = st.secrets.get("supabase", {}).get("key", "YOUR_SUPABASE_KEY")
    return create_client(url, key)

try:
    supabase: Client = init_connection()
except Exception:
    st.warning("⚠️ Database connection failed. Check your secrets.")
    st.stop()

# Initialize session state for authentication
if 'student_auth' not in st.session_state:
    st.session_state.student_auth = False
    st.session_state.student_usn = ""
    st.session_state.student_name = ""

# ==========================================
# 2. IMAGE PROCESSING ENGINE ("The Washing Machine")
# ==========================================
def process_passport_photo(uploaded_file):
    """Converts, center-crops to 3:4 ratio, resizes to 600x800, and compresses to JPG."""
    try:
        img = Image.open(uploaded_file)
        
        # Strip alpha channels (transparency in PNGs) and force standard RGB
        if img.mode != 'RGB':
            img = img.convert('RGB')
            
        # Standard Passport Aspect Ratio (3:4)
        target_size = (600, 800)
        
        # ImageOps.fit automatically center-crops the image to the exact ratio without stretching
        img_cropped = ImageOps.fit(img, target_size, method=Image.Resampling.LANCZOS)
        
        # Compress and save to in-memory byte buffer
        output_buffer = io.BytesIO()
        img_cropped.save(output_buffer, format='JPEG', quality=85, optimize=True)
        output_buffer.seek(0)
        
        return output_buffer
    except Exception as e:
        st.error(f"Image processing failed: {e}")
        return None

# ==========================================
# 3. USER INTERFACE & LOGIC
# ==========================================
st.image("https://upload.wikimedia.org/wikipedia/commons/thumb/a/a7/AMC_Engineering_College_Logo.png/1200px-AMC_Engineering_College_Logo.png", width=80)
st.title("📸 Official Photo Portal")
st.markdown("Upload your formal passport-size photograph for your Hall Ticket and Academic Records.")

# --- STEP 1: SECURITY GATE ---
if not st.session_state.student_auth:
    st.info("🔒 Please verify your identity to proceed.")
    
    with st.form("auth_form"):
        usn_input = st.text_input("USN (University Serial Number)", placeholder="e.g., 1AM26EC001").strip().upper()
        # Using Phone Number as the 2FA secret (You can change this to DOB based on your DB completeness)
        phone_input = st.text_input("Registered Phone Number", placeholder="10-digit mobile number").strip()
        
        submitted = st.form_submit_button("Verify Identity", type="primary", use_container_width=True)
        
        if submitted:
            if not usn_input or not phone_input:
                st.error("⚠️ Both fields are required.")
            else:
                with st.spinner("Verifying records..."):
                    res = supabase.table("master_students").select("usn, full_name, phone").eq("usn", usn_input).execute()
                    
                    if not res.data:
                        st.error("❌ USN not found in the master database.")
                    else:
                        student_record = res.data[0]
                        db_phone = str(student_record.get('phone', '')).strip()
                        
                        # Fallback bypass if phone isn't in DB yet (Remove in production once data is clean)
                        if db_phone == 'None' or db_phone == '':
                            st.warning("⚠️ No phone number registered in database. Allowing one-time bypass for setup.")
                            db_phone = phone_input 
                            
                        if phone_input[-5:] == db_phone[-5:]: # Checking last 5 digits for flexibility
                            st.session_state.student_auth = True
                            st.session_state.student_usn = student_record['usn']
                            st.session_state.student_name = student_record['full_name']
                            st.rerun()
                        else:
                            st.error("❌ Phone number does not match our records.")

# --- STEP 2: SECURE UPLOAD BOOTH ---
if st.session_state.student_auth:
    st.success(f"✅ Welcome, **{st.session_state.student_name}** (`{st.session_state.student_usn}`)")
    
    if st.button("🚪 Logout / Wrong Student"):
        st.session_state.student_auth = False
        st.session_state.student_usn = ""
        st.rerun()
        
    st.markdown("---")
    st.subheader("Upload Photograph")
    st.markdown("""
    **Guidelines:**
    * 👔 Professional attire required.
    * 🟦 Light or solid background.
    * 👤 Face must be clearly visible and centered.
    """)
    
    # Strictly File Uploader (No st.camera_input)
    uploaded_file = st.file_uploader("Choose a file", type=['jpg', 'jpeg', 'png', 'webp'])
    
    if uploaded_file is not None:
        st.info("⚙️ Processing image (auto-cropping and optimizing)...")
        
        processed_bytes = process_passport_photo(uploaded_file)
        
        if processed_bytes:
            # Show the student exactly what the final cropped image looks like
            st.image(processed_bytes, caption="Final Portrait Preview", width=250)
            
            if st.button("☁️ Confirm & Upload to Database", type="primary", use_container_width=True):
                with st.spinner("Uploading securely..."):
                    file_name = f"{st.session_state.student_usn}.jpg"
                    
                    try:
                        # Upload to Supabase Storage (upsert=true overwrites any old photo)
                        res = supabase.storage.from_("StakeHolders_Photos").upload(
                            file=processed_bytes.getvalue(),
                            path=file_name,
                            file_options={"content-type": "image/jpeg", "upsert": "true"}
                        )
                        st.success("🎉 **Success!** Your photo has been officially updated.")
                        st.balloons()
                    except Exception as e:
                        if "Duplicate" in str(e):
                            # In case upsert flag doesn't bypass Supabase API quirks, do a manual update
                            supabase.storage.from_("StakeHolders_Photos").update(
                                file=processed_bytes.getvalue(),
                                path=file_name,
                                file_options={"content-type": "image/jpeg"}
                            )
                            st.success("🎉 **Success!** Your existing photo has been successfully replaced.")
                            st.balloons()
                        else:
                            st.error(f"❌ Upload failed: {e}")