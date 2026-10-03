import streamlit as st
import io
import pandas as pd
from datetime import datetime
from PIL import Image, ImageOps
from streamlit_cropper import st_cropper
from supabase import create_client, Client

# ==========================================
# 1. SETUP & CONFIGURATION
# ==========================================
st.set_page_config(page_title="Student Photo Portal", page_icon="📸", layout="centered")

# 🟢 SECRET ADMIN PIN (Change this to whatever you want)
ADMIN_PIN = "9999"

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
    st.session_state.is_admin = False
    st.session_state.student_usn = ""
    st.session_state.student_name = ""
    st.session_state.upload_count = 0

# ==========================================
# 2. USER INTERFACE & LOGIC
# ==========================================

st.title("📸 AMCEC Official Photo Portal")
st.markdown("Upload your formal passport-size photograph for your Hall Ticket and Academic Records.")

# --- STEP 1: SECURITY GATE ---
if not st.session_state.student_auth and not st.session_state.is_admin:
    st.info("🔒 Please verify your identity to proceed.")
    
    with st.form("auth_form"):
        usn_input = st.text_input("User Name", placeholder="e.g., TMP-EC-001 or 1AM26EC001").strip().upper()
        pin_input = st.text_input("4-Digit PIN", placeholder="Found on your printed application form", type="password").strip()
        
        submitted = st.form_submit_button("Verify Identity", type="primary", use_container_width=True)
        
        if submitted:
            if not usn_input or not pin_input:
                st.error("⚠️ Both fields are required.")
            elif usn_input == "ADMIN" and pin_input == ADMIN_PIN:
                # 🟢 SECRET ADMIN LOGIN TRIGGER
                st.session_state.is_admin = True
                st.rerun()
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
                            st.error("❌ Incorrect PIN. Please check your printed application form.")

# --- STEP 2: SECRET ADMIN DASHBOARD ---
elif st.session_state.is_admin:
    st.success("✅ Logged in as Administrator")
    
    if st.button("🚪 Exit Admin Panel"):
        st.session_state.is_admin = False
        st.rerun()
        
    st.markdown("---")
    st.subheader("📊 Live Upload Analytics")
    
    # 🟢 PAGINATED FETCH LOOP (Bypasses 1,000 limit)
    with st.spinner("Fetching live database metrics (bypassing limits)..."):
        all_data = []
        start = 0
        step = 1000
        
        while True:
            res = supabase.table("master_students").select("usn, full_name, branch_code, photo_upload_count, last_photo_upload").range(start, start + step - 1).execute()
            if not res.data:
                break
            all_data.extend(res.data)
            if len(res.data) < step:
                break
            start += step
            
        df = pd.DataFrame(all_data)
        
        if not df.empty:
            df['photo_upload_count'] = df['photo_upload_count'].fillna(0).astype(int)
            total_students = len(df)
            total_uploaded = len(df[df['photo_upload_count'] > 0])
            total_pending = total_students - total_uploaded
            completion_rate = (total_uploaded / total_students) * 100 if total_students > 0 else 0
            
            # Key Metrics
            col1, col2, col3, col4 = st.columns(4)
            col1.metric("Total Students", total_students)
            col2.metric("Photos Uploaded", total_uploaded)
            col3.metric("Pending Uploads", total_pending)
            col4.metric("Completion Rate", f"{completion_rate:.1f}%")
            
            st.divider()
            
            # Tabular breakdown
            tab1, tab2, tab3 = st.tabs(["📋 Upload Audit Log", "⚠️ Multiple Replacements", "⏳ Pending Students"])
            
            with tab1:
                st.markdown("**Recent Upload Activity**")
                uploaded_df = df[df['photo_upload_count'] > 0].sort_values(by="last_photo_upload", ascending=False)
                uploaded_df.rename(columns={"usn": "USN", "full_name": "Name", "branch_code": "Branch", "photo_upload_count": "Uploads", "last_photo_upload": "Last Upload Time"}, inplace=True)
                st.dataframe(uploaded_df, use_container_width=True, hide_index=True)
                
            with tab2:
                st.markdown("**Students who changed their photo multiple times**")
                suspicious_df = df[df['photo_upload_count'] > 1].sort_values(by="photo_upload_count", ascending=False)
                suspicious_df.rename(columns={"usn": "USN", "full_name": "Name", "photo_upload_count": "Times Replaced"}, inplace=True)
                st.dataframe(suspicious_df[['USN', 'Name', 'Times Replaced']], use_container_width=True, hide_index=True)
                
            with tab3:
                st.markdown("**Students yet to upload a photo**")
                pending_df = df[df['photo_upload_count'] == 0]
                st.dataframe(pending_df[['usn', 'full_name', 'branch_code']], use_container_width=True, hide_index=True)
        else:
            st.warning("No student records found in the database.")

# --- STEP 3: SECURE UPLOAD BOOTH (STUDENT VIEW) ---
elif st.session_state.student_auth:
    st.success(f"✅ Welcome, **{st.session_state.student_name}** (`{st.session_state.student_usn}`)")
    
    if st.button("🚪 Logout / Wrong Student"):
        st.session_state.student_auth = False
        st.session_state.student_usn = ""
        st.rerun()
        
    st.markdown("---")
    st.subheader("Upload & Crop Photograph")
    
    if st.session_state.upload_count > 0:
        st.info(f"🔄 You have already uploaded a photo. Uploading a new one will replace your existing formal photo. (Uploads so far: {st.session_state.upload_count})")
        
    st.markdown("""
    **Guidelines:**
    * 👔 Professional attire required.
    * 🟦 Light or solid background.
    * 👤 Face must be clearly visible and centered.
    * ✂️ **You must crop your photo using the tool below.**
    """)
    
    input_method = st.radio("Choose Photo Source:", ["Upload a File", "Use Web Camera"], horizontal=True)

    uploaded_file = None
    if input_method == "Upload a File":
        uploaded_file = st.file_uploader("Upload an image (JPG/PNG)", type=['jpg', 'jpeg', 'png', 'webp'])
    else:
        uploaded_file = st.camera_input("Take a picture")
    
    if uploaded_file is not None:
        MAX_FILE_SIZE = 5 * 1024 * 1024  # Increased to 5MB to allow high-res originals before cropping
        
        if uploaded_file.size > MAX_FILE_SIZE:
            current_size_mb = uploaded_file.size / (1024 * 1024)
            st.error(f"❌ **File Too Large!** Your image is {current_size_mb:.2f} MB. Please compress the image to under 5 MB and try again.")
        else:
            try:
                # Load image into PIL for the cropper
                img = Image.open(uploaded_file)
                if img.mode != 'RGB': img = img.convert('RGB')

                st.markdown("### ✂️ Step 1: Crop Your Photo")
                st.info("Drag the corners of the blue box to frame your face. The box is strictly locked to the standard ID photo size (3:4 ratio).")
                
                # Render the interactive crop tool
                cropped_img = st_cropper(
                    img, 
                    aspect_ratio=(3, 4), 
                    box_color='#3b82f6', # Tailwind Blue
                    return_type='image'
                )
                
                st.divider()
                
                # 3. Final Preview & Approval
                st.markdown("### 👀 Step 2: Review & Submit")
                
                col1, col2 = st.columns([1, 2])
                with col1:
                    st.write("**Final ID Preview:**")
                    # Display the exact cropped result to the student
                    st.image(cropped_img, use_column_width=True)
                    
                with col2:
                    st.warning("Make sure your face is clearly visible, well-lit, and directly facing the camera. Blurry or poorly cropped photos will be rejected by the administration.")
                    
                    # Require manual confirmation before upload
                    if st.checkbox("I confirm this photo is clear, perfectly cropped, and meets college guidelines."):
                        if st.button("☁️ Confirm & Upload to Database", type="primary", use_container_width=True):
                            with st.spinner("Optimizing and uploading securely..."):
                                
                                # Process the already-cropped image to standardize size (600x800) and compress to JPG
                                target_size = (600, 800)
                                final_img = ImageOps.fit(cropped_img, target_size, method=Image.Resampling.LANCZOS)
                                
                                img_byte_arr = io.BytesIO()
                                final_img.save(img_byte_arr, format='JPEG', quality=85, optimize=True)
                                final_image_bytes = img_byte_arr.getvalue()
                                
                                file_name = f"{st.session_state.student_usn}.jpg"
                                try:
                                    # Push to Storage Bucket
                                    res = supabase.storage.from_("StakeHolders_Photos").upload(
                                        file=final_image_bytes,
                                        path=file_name,
                                        file_options={"content-type": "image/jpeg", "upsert": "true"}
                                    )
                                    
                                    # UPDATE AUDIT COUNTER IN DATABASE
                                    new_count = st.session_state.upload_count + 1
                                    supabase.table("master_students").update({
                                        "photo_upload_count": new_count,
                                        "last_photo_upload": datetime.now().isoformat()
                                    }).eq("usn", st.session_state.student_usn).execute()
                                    
                                    st.session_state.upload_count = new_count
                                    
                                    st.success("🎉 **Success!** Your perfectly cropped photo has been officially updated.")
                                    st.balloons()
                                except Exception as e:
                                    if "Duplicate" in str(e) or "already exists" in str(e):
                                        # Push replacement to Storage Bucket
                                        supabase.storage.from_("StakeHolders_Photos").update(
                                            file=final_image_bytes,
                                            path=file_name,
                                            file_options={"content-type": "image/jpeg"}
                                        )
                                        
                                        # UPDATE AUDIT COUNTER IN DATABASE
                                        new_count = st.session_state.upload_count + 1
                                        supabase.table("master_students").update({
                                            "photo_upload_count": new_count,
                                            "last_photo_upload": datetime.now().isoformat()
                                        }).eq("usn", st.session_state.student_usn).execute()
                                        
                                        st.session_state.upload_count = new_count
                                        
                                        st.success("🎉 **Success!** Your existing photo has been successfully replaced.")
                                        st.balloons()
                                    else:
                                        st.error(f"❌ Upload failed: {e}")
            except Exception as e:
                 st.error(f"❌ Error loading image: {e}")
