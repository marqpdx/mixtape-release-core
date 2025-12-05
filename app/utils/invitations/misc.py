from django.core.mail import send_mail


def send_contact(request):

    print("in contact.utils.send_invitation, rq.data", request.data)

    context = {}
    if request.method == "POST":
        name = "asdfasdf" # request.data['name']
        email = "connect@unfurlproject.com" # request.data['email']
        message = "From: "+ email + "\n"
        message += "Sender Name: "+ name + "\n\r\n\r"
        message += "-------------------------------------------------------"
        message += "\n\r\n\r"

        message += "homegrown" # request.data['message']

        try:
            send_mail(
                "SITE Inquiry - "+ name,# subject,
                message,#message
                email,# from email
                ["marqpdx@gmail.com"],# to email,
                #fail_silently=False
            )
            context = {"mail_response":True}
        except Exception as err:
            raise err
    return context
