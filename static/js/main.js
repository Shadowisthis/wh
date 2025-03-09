document.addEventListener('DOMContentLoaded', function() {
    // 文件上传处理
    const uploadBox = document.querySelector('.upload-box');
    const fileInput = document.querySelector('#file-input');
    
    if(uploadBox && fileInput) {
        uploadBox.addEventListener('click', () => fileInput.click());
        
        fileInput.addEventListener('change', function() {
            if(this.files && this.files[0]) {
                document.querySelector('#upload-form').submit();
            }
        });
    }

    // 动态消息提示
    setTimeout(() => {
        const alerts = document.querySelectorAll('.alert');
        alerts.forEach(alert => alert.remove());
    }, 3000);
});